"""Anade a esquema_fb.json el id real (slot del vtable) y el valor por defecto de cada campo,
leyendolos del codigo maquina de cada getter generado por flatc."""
import sys, json, struct
sys.path.insert(0,'rev')
from mrrev import *
OFFSET=real(name2addrs['FlatBuffers.Table::__offset'][0])
S=json.load(open(sys.argv[1])); out=sys.argv[2]
stats=dict(ok=0, sin_getter=0, raros=0); nodef=[]; gaps=[]
def analizar(a):
    L=insns(a); idx=None
    for i,ins in enumerate(L):
        if ins.mnemonic=='bl' and int(ins.op_str[1:],16)==OFFSET: idx=i; break
    if idx is None: return None
    vt=None
    for ins in reversed(L[:idx]):
        if ins.mnemonic=='mov' and ins.op_str.startswith('w1, #'): vt=int(ins.op_str.split('#')[1],16); break
    if vt is None: return None
    # rama por defecto
    blk=None
    for j in range(idx+1,min(idx+5,len(L))):
        ins=L[j]
        if ins.mnemonic=='cbz': tgt=int(ins.op_str.split('#')[1],16); blk=[x for x in L if x.address>=tgt]; break
        if ins.mnemonic=='cbnz': blk=L[j+1:]; break
    default=0; adrp={}
    if blk is not None:
        for ins in blk[:14]:
            m,o=ins.mnemonic,ins.op_str
            if m=='adrp': adrp[o.split(',')[0]]=int(o.split('#')[1],16)
            elif m in('mov','movz','movn') and (o.startswith('w0, #') or o.startswith('x0, #')):
                default=int(o.split('#')[1],16)
            elif m=='movk' and (o.startswith('w0, #') or o.startswith('x0, #')):
                parts=o.split(','); imm=int(parts[1].strip()[1:],16); sh=int(parts[2].split('#')[1]) if len(parts)>2 else 0
                default=(default & ~(0xFFFF<<sh)) | (imm<<sh)
            elif m=='fmov' and (o.startswith('s0, #') or o.startswith('d0, #')): default=float(o.split('#')[1])
            elif m=='ldr' and (o.startswith('s0, [') or o.startswith('d0, [')):
                reg=o.split('[')[1].split(',')[0].strip(' ]'); off=int(o.split('#')[1].rstrip(']'),16) if '#' in o else 0
                if reg in adrp:
                    va=adrp[reg]+off; raw=data[va2off(va):va2off(va)+8]
                    default=struct.unpack('<f',raw[:4])[0] if o.startswith('s0') else struct.unpack('<d',raw)[0]
            elif m in('ret','b','bl'): break
    return (vt-4)//2, default
for tname,t in S['tables'].items():
    prev=-1
    for f in t['fields']:
        if f['kind']=='union':
            tf=next((x for x in t['fields'] if x['kind']=='union_type' and x['name']==f['name']+'Type'),None)
            f['id']=tf['id']+1 if tf and 'id' in tf else prev+1; prev=f['id']; continue
        cands=name2addrs.get(f'MetalFury.FBTypes.{tname}::get_{f["name"]}',[])+name2addrs.get(f'MetalFury.FBTypes.{tname}::{f["name"]}',[])
        r=None
        for a in cands:
            r=analizar(a)
            if r: break
        if r is None:
            stats['sin_getter']+=1; f['id']=prev+1; prev=f['id']; nodef.append(f'{tname}.{f["name"]}'); continue
        fid,default=r
        if fid!=prev+1: gaps.append((tname,f['name'],prev+1,fid))
        f['id']=fid; prev=fid; stats['ok']+=1
        if f['kind'] in('scalar','enum','union_type') and default!=0:
            if f.get('type')=='bool': default=bool(default)
            elif isinstance(default,int):
                base=f['type'] if f['kind']=='scalar' else S['enums'].get(f['type'],{}).get('base','int')
                bits={'byte':8,'ubyte':8,'short':16,'ushort':16,'int':32,'uint':32,'long':64,'ulong':64}.get(base,32)
                default&=(1<<bits)-1
                if base in('byte','short','int','long') and default>=1<<(bits-1): default-=1<<bits
            f['default']=default
json.dump(S,open(out,'w'),indent=1)
print(stats); print('sin getter:',nodef[:15]); print('saltos de id (campos obsoletos):',len(gaps),gaps[:40])
nz=[(tn,f['name'],f['default']) for tn,t in S['tables'].items() for f in t['fields'] if 'default' in f]
print('campos con defecto distinto de 0:',len(nz))
for x in nz: print('  ',x)
