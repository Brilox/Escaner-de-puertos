# utilidades de ingenieria inversa compartidas
import json, bisect, re, struct
from elftools.elf.elffile import ELFFile
from capstone import *
from capstone.arm64 import *
LIB='apk_in/out/x/lib/arm64-v8a/libil2cpp.so'
data=open('/tmp/il2cpp_reloc.bin','rb').read(); elf=ELFFile(open(LIB,'rb'))
segs=[(s['p_vaddr'],s['p_offset'],s['p_filesz']) for s in elf.iter_segments() if s['p_type']=='PT_LOAD']
def va2off(va):
    for v,o,fs in segs:
        if v<=va<v+fs: return o+(va-v)
T=json.load(open('apk_in/out/method_addrs.json')); table={int(k,16):v for k,v in T.items()}; addrs=sorted(table)
name2addrs={}
for a,ns in table.items():
    for n in ns: name2addrs.setdefault(n,[]).append(a)
cs=Cs(CS_ARCH_ARM64,CS_MODE_ARM); cs.detail=True
TEXT=(0x17f9e00,0x17f9e00+0x87c880)   # seccion .text: cifrada con XOR 0xB6 (runtime y thunks de structs)
def code(va,n):
    b=data[va2off(va):va2off(va)+n]
    return bytes(x^0xB6 for x in b) if TEXT[0]<=va<TEXT[1] else b
def real(a):
    """Si a es un thunk 'add x0,x0,#0x10; b destino' (metodos de struct), devuelve el destino."""
    if TEXT[0]<=a<TEXT[1]:
        w0,w1=struct.unpack('<II',code(a,8))
        if w0==0x91004000 and (w1>>26)==0b000101:
            imm=w1&0x3FFFFFF
            if imm>=1<<25: imm-=1<<26
            return a+4+imm*4
    return a
real_starts=None
def body(a):
    global real_starts
    if real_starts is None:
        real_starts=sorted(set(addrs)|{real(x) for x in addrs if TEXT[0]<=x<TEXT[1]})
    i=bisect.bisect_right(real_starts,a); end=real_starts[i] if i<len(real_starts) else a+0x1000
    return code(a,min(end-a,0x8000)), end
def insns(a):
    a=real(a); b,end=body(a); return list(cs.disasm(b,a))
def dis(a,limit=10000):
    out=[]
    for ins in insns(a):
        s=f'{ins.address:x}: {ins.mnemonic} {ins.op_str}'
        if ins.mnemonic in('bl','b'):
            try:
                t=int(ins.op_str.replace('#',''),16)
                if t in table: s+='   ; -> '+table[t][0]
                elif t in real2name: s+='   ; -> '+real2name[t]
            except: pass
        out.append(s)
        if len(out)>=limit: break
    return out
def find(pat):
    r=re.compile(pat); return sorted((a,n) for n,al in name2addrs.items() if r.search(n) for a in al)

real2name={}
for _a in addrs:
    if TEXT[0]<=_a<TEXT[1]:
        _r=real(_a)
        if _r!=_a: real2name[_r]=table[_a][0]

def resumen(a, solo_llamadas=True):
    """Vista compacta: llamadas con nombre, comparaciones y saltos condicionales."""
    out=[]
    for ins in insns(a):
        m,o=ins.mnemonic,ins.op_str; s=None
        if m in('bl','b') and o.startswith('#'):
            t=int(o[1:],16); n=table.get(t,[None])[0] or real2name.get(t)
            if n: s=f'{ins.address:x}: {m} {n}'
            elif m=='b' and not (insns_range[0]<=t<insns_range[1]): s=f'{ins.address:x}: b {hex(t)}'
        elif m in('cmp','tst','ccmp') or m.startswith('b.') or m in('cbz','cbnz','tbz','tbnz','ret','blr'): s=f'{ins.address:x}: {m} {o}'
        elif m in('ldr','ldrb','ldrh','ldrsw','str','strb','strh') and ('x19' in o or 'x20' in o or 'x21' in o or 'x22' in o or 'x0,' in o) and '#0x' in o and 'sp' not in o: s=f'{ins.address:x}: {m} {o}'
        elif m in ('mov','movz') and '#' in o and o.split(',')[0] in ('w1','w2','w3','w4'): s=f'{ins.address:x}: {m} {o}'
        if s: out.append(s)
    return out
insns_range=(0,0)
def ver(nombre_regex, maxn=6, limite=400, completo=False):
    for a,n in find(nombre_regex)[:maxn]:
        global insns_range
        r=real(a); b,end=body(r); insns_range=(r,end)
        L=dis(a) if completo else resumen(a)
        print(f'\n### {n} @ {hex(r)} ({(end-r)//4} instr)'); print('\n'.join(L[:limite]))

# ---- mapa de "metadata usages": slot global -> literal de texto / clase / metodo / campo
MD=open('apk_in/out/x/assets/bin/Data/Managed/Metadata/global-metadata.dat','rb').read()
_H=struct.unpack_from('<64I',MD,0)
def _cstr(i): o=_H[6]+i; return MD[o:MD.index(b'\0',o)].decode('utf-8','replace')
_TYPES_VA,_TYPES_CNT=0x75f7be8,0x1d1a9
_tptrs=None
def _tipo_nombre(ti,tname):
    global _tptrs
    if _tptrs is None: _tptrs=struct.unpack_from(f'<{_TYPES_CNT}Q',data,va2off(_TYPES_VA))
    try:
        d,bits=struct.unpack_from('<QI',data,va2off(_tptrs[ti])); te=(bits>>16)&0xff
        if te>=0x80: te^=0xb6; d^=0xB6B6B6B6B6B6B6B6
        if te in(0x11,0x12): return tname(d&0xFFFFFFFF)
        return 'tipo%#x'%te
    except Exception: return '?'
def _build_usages():
    litOff,datOff=_H[2],_H[4]; tdOff=_H[40]; mOff=_H[12]; fOff=_H[24]
    pairsOff,pairsCnt=_H[50],_H[51]//8
    MU_VA,MU_CNT=0x76e0930,0x1bd67
    slots=struct.unpack_from(f'<{MU_CNT}Q',data,va2off(MU_VA))
    tdn={}
    def tname(i):
        if i not in tdn:
            f=struct.unpack_from('<2I',MD,tdOff+i*100); ns=_cstr(f[1]); tdn[i]=(ns+'.' if ns else '')+_cstr(f[0])
        return tdn[i]
    m={}
    for k in range(pairsCnt):
        dest,enc=struct.unpack_from('<II',MD,pairsOff+k*8); kind=enc>>29; idx=enc&0x1FFFFFFF
        if dest>=MU_CNT: continue
        if kind==5:
            ln,di=struct.unpack_from('<2I',MD,litOff+idx*8); v='"'+MD[datOff+di:datOff+di+ln].decode('utf-8','replace')+'"'
        elif kind==3:
            f=struct.unpack_from('<2I',MD,mOff+idx*52); v='metodo '+tname(f[1])+'::'+_cstr(f[0])
        elif kind==1: v='clase '+_tipo_nombre(idx,tname)
        elif kind==2: v='tipo#'+str(idx)
        elif kind==4: v='campo#'+str(idx)
        elif kind==6: v='metodoRef#'+str(idx)
        else: v='?'
        m[slots[dest]]=v
    return m
USOS=_build_usages()
def anotado(a, limite=100000):
    """Desensamblado completo con literales y nombres resueltos."""
    out=[]; adrp={}
    for ins in insns(a):
        m,o=ins.mnemonic,ins.op_str; s=f'{ins.address:x}: {m} {o}'
        if m=='adrp': adrp[o.split(',')[0]]=int(o.split('#')[1],16)
        elif m=='ldr' and '[' in o:
            reg=o.split('[')[1].split(',')[0].strip(' ]')
            if reg in adrp and '#' in o.split('[')[1]:
                va=adrp[reg]+int(o.split('#')[-1].rstrip(']!'),16)
                off_=va2off(va)
                if off_ is not None:
                    slot=struct.unpack_from('<Q',data,off_)[0]
                    if slot in USOS: s+='      ; '+USOS[slot]
                    elif va in USOS: s+='      ; '+USOS[va]
            dst=o.split(',')[0]
            if dst in adrp and dst!=reg: adrp.pop(dst,None)
            elif dst==reg: adrp.pop(dst,None)
        elif m in('bl','b') and o.startswith('#'):
            t=int(o[1:],16); n=table.get(t,[None])[0] or real2name.get(t)
            if n: s+='   ; -> '+n
        out.append(s)
        if len(out)>=limite: break
    return out
def literales(nombre_regex, maxn=3):
    """Literales de texto que usa un metodo, en orden."""
    for a,n in find(nombre_regex)[:maxn]:
        print('###',n); print('   ',[l.split('; ')[1] for l in anotado(a) if '; "' in l])

def campos(ns, nombre):
    """{offset: nombre_de_campo} de una clase (offsets decodificados con XOR 0xB6B6B6B6)."""
    tdOff=_H[40]; tdCnt=_H[41]//100; fOff=_H[24]
    for t in range(tdCnt):
        f=struct.unpack_from('<19I8H2I',MD,tdOff+t*100)
        if _cstr(f[0])==nombre and _cstr(f[1])==ns:
            p=struct.unpack_from('<Q',data,va2off(0x7e4d708)+t*8)[0]
            if not p: return {}
            offs=struct.unpack_from(f'<{f[21]}I',data,va2off(p))
            return {(offs[k]^0xB6B6B6B6)&0xFFFFFFFF: _cstr(struct.unpack_from('<I',MD,fOff+(f[11]+k)*12)[0]) for k in range(f[21])}
    return {}

def notas(nombre_regex, maxn=4, limite=300, filtro=None):
    """Solo las lineas anotadas (llamadas con nombre, literales, clases) de los metodos que coinciden."""
    for a,n in find(nombre_regex)[:maxn]:
        L=[l for l in anotado(a) if '; ' in l and not any(x in l for x in ('get_app','::get_internetClient','op_Implicit','metodoRef#'))]
        if filtro: L=[l for l in L if filtro(l)]
        print(f'\n### {n} @ {hex(real(a))}'); print('\n'.join(x[:175] for x in L[:limite]))

def medio(nombre_regex, maxn=4, limite=400, exacto=None):
    """Vista intermedia: llamadas, literales, comparaciones, inmediatos y accesos a campos (sin sp)."""
    for a,n in find(nombre_regex)[:maxn]:
        if exacto and n!=exacto: continue
        out=[]
        for l in anotado(a):
            ins=l.split(': ',1)[1]; m=ins.split(' ')[0]
            if '; ' in l:
                if any(x in l for x in ('get_app','op_Implicit')): continue
                out.append(l)
            elif m in('cmp','ccmp','tst','cbz','cbnz','tbz','tbnz','ret','blr','br','csel','cset','cinc') or m.startswith('b.'): out.append(l)
            elif m in('mov','movz','movk','movn','orr','and','add','sub','lsl','lsr','asr','eor','mul','madd','sdiv','udiv','ubfx','sbfx','bfi','rev','rev16','sxtw','uxtb','uxth','neg') and '#' in ins: out.append(l)
            elif m in('ldr','ldrb','ldrh','ldrsw','ldrsb','ldrsh','str','strb','strh','ldp','stp','ldur','stur','sturb','ldurb','sturh','ldurh') and 'sp' not in ins and '#' in ins and 'x29' not in ins: out.append(l)
            elif m=='b' : out.append(l)
        print(f'\n### {n} @ {hex(real(a))}'); print('\n'.join(x[:150] for x in out[:limite]))

def enum_valores(ns, nombre):
    """{nombre: valor} de un enum, leyendo los valores constantes del metadata."""
    tdOff=_H[40]; tdCnt=_H[41]//100; fOff=_H[24]; fdOff,fdCnt=_H[16],_H[17]//12; dataOff=_H[18]
    fdv={}
    for i in range(fdCnt):
        fi,ti,di=struct.unpack_from('<3i',MD,fdOff+i*12); fdv[fi]=di
    for t in range(tdCnt):
        f=struct.unpack_from('<19I8H2I',MD,tdOff+t*100)
        if _cstr(f[0])==nombre and _cstr(f[1])==ns:
            out={}
            for k in range(f[21]):
                fi=f[11]+k; nm=_cstr(struct.unpack_from('<I',MD,fOff+fi*12)[0])
                if nm=='value__' or fi not in fdv: continue
                out[nm]=MD[dataOff+fdv[fi]]
            return out
    return {}
def llamadores(nombre):
    """Metodos que llaman (bl) a la funcion dada."""
    import numpy as np
    tgt=real(name2addrs[nombre][0]); res=set()
    for s in elf.iter_sections():
        if not s['sh_flags']&0x4 or s['sh_size']<8 or s.name=='.text': continue
        w=np.frombuffer(data,dtype='<u4',count=s['sh_size']//4,offset=s['sh_offset'])
        isbl=((w>>26)==0b100101)|((w>>26)==0b000101); imm=(w&0x3FFFFFF).astype(np.int64); imm=np.where(imm>=1<<25,imm-(1<<26),imm)
        pcs=s['sh_addr']+np.arange(len(w),dtype=np.int64)*4
        for i in np.nonzero(isbl & (pcs+imm*4==tgt))[0]:
            pc=int(pcs[i]); k=bisect.bisect_right(real_starts,pc)-1; st=real_starts[k]
            res.add(table.get(st,[None])[0] or real2name.get(st) or hex(st))
    return sorted(res)
