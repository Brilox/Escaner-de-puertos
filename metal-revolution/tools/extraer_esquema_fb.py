#!/usr/bin/env python3
"""Extrae el esquema FlatBuffers (MetalFury.FBTypes) desde global-metadata.dat + libil2cpp.so (relocado).
Salida: JSON {tables:{name:{fields:[{name,kind,type,elem}]}}, enums:{name:{base, values:{name:int}}}, unions:{name:[...]}}"""
import struct, json, sys, collections
from elftools.elf.elffile import ELFFile
META, LIB, RELOC, TYPES_VA, TYPES_CNT, OUT = sys.argv[1:7]
TYPES_VA=int(TYPES_VA,16); TYPES_CNT=int(TYPES_CNT,16)
md=open(META,'rb').read(); H=struct.unpack_from('<50I',md,0); strOff=H[6]
def cstr(i): o=strOff+i; return md[o:md.index(b'\0',o)].decode('utf-8','replace')
data=open(RELOC,'rb').read(); elf=ELFFile(open(LIB,'rb'))
segs=[(s['p_vaddr'],s['p_offset'],s['p_filesz']) for s in elf.iter_segments() if s['p_type']=='PT_LOAD']
def va2off(va):
    for v,o,fs in segs:
        if v<=va<v+fs: return o+(va-v)
ptrs=struct.unpack_from(f'<{TYPES_CNT}Q',data,va2off(TYPES_VA)); ptrset=set()
tdOff=H[40]; tdCnt=H[41]//100; mOff=H[12]; pOff=H[22]; fOff=H[24]; fdOff,fdCnt=H[16],H[17]//12; dataOff=H[18]
TD={}
for t in range(tdCnt):
    f=struct.unpack_from('<19I8H2I',md,tdOff+t*100); TD[t]=dict(name=cstr(f[0]),ns=cstr(f[1]),byval=f[2],parent=f[5],fieldStart=f[11],methodStart=f[12],mcount=f[19],fcount=f[21],idx=t)
SCALAR={2:'bool',3:'char',4:'byte',5:'ubyte',6:'short',7:'ushort',8:'int',9:'uint',10:'long',11:'ulong',12:'float',13:'double',14:'string'}
def il2type(ti):
    """-> (kind, name) kind in scalar/string/class/valuetype/generic/other"""
    p=ptrs[ti]; d,bits=struct.unpack_from('<QI',data,va2off(p)); te=(bits>>16)&0xff
    if te>=0x80: te^=0xb6; d^=0xB6B6B6B6B6B6B6B6
    if te in SCALAR: return ('string' if te==14 else 'scalar', SCALAR[te])
    if te in (0x11,0x12):
        td=TD[d & 0xFFFFFFFF]; return ('valuetype' if te==0x11 else 'class', td['name'], td)
    if te==0x15:  # GENERICINST: Il2CppGenericClass* -> typeDefinitionIndex, context.class_inst -> {argc, argv}
        gc=va2off(d)
        if gc is None: return ('other','genericinst?')
        tdi=struct.unpack_from('<i',data,gc)[0]; inst=struct.unpack_from('<Q',data,gc+8)[0]
        gname=TD[tdi]['name'] if 0<=tdi<len(TD) else '?'
        args=[]
        if inst and va2off(inst):
            argc,argv=struct.unpack_from('<IxxxxQ',data,va2off(inst))
            if argv and va2off(argv) and argc<16:
                for q in range(argc):
                    tp=struct.unpack_from('<Q',data,va2off(argv)+q*8)[0]
                    try: args.append(il2type_ptr(tp))
                    except Exception: args.append(('other','?'))
        if gname.startswith('Nullable') and args: return args[0]
        return ('generic', gname, args)
    return ('other', hex(te))
def il2type_ptr(p):
    d,bits=struct.unpack_from('<QI',data,va2off(p)); te=(bits>>16)&0xff
    if te>=0x80: te^=0xb6; d^=0xB6B6B6B6B6B6B6B6
    if te in SCALAR: return ('string' if te==14 else 'scalar', SCALAR[te])
    if te in (0x11,0x12):
        td=TD[d & 0xFFFFFFFF]; return ('valuetype' if te==0x11 else 'class', td['name'], td)
    return ('other', hex(te))
def enum_values(td):
    vals={}
    for k in range(td['fcount']):
        fi=td['fieldStart']+k; name=cstr(struct.unpack_from('<I',md,fOff+fi*12)[0])
        if name=='value__': continue
        vals[name]=None
    # default values table
    return vals
# index fieldDefaultValues by fieldIndex
FDV={}
for i in range(fdCnt):
    fi,ti,di=struct.unpack_from('<3i',md,fdOff+i*12); FDV[fi]=(ti,di)
def enum_def(td):
    base='int'; vals={}
    for k in range(td['fcount']):
        fi=td['fieldStart']+k; nm,ti,_=struct.unpack_from('<3I',md,fOff+fi*12); name=cstr(nm)
        if name=='value__': base=il2type(ti)[1]; continue
        if fi in FDV:
            dti,di=FDV[fi]; kind,tn=il2type(dti)[:2]
            fmt={'bool':'<?','byte':'<b','ubyte':'<B','short':'<h','ushort':'<H','int':'<i','uint':'<I','long':'<q','ulong':'<Q'}.get(tn,'<i')
            vals[name]=struct.unpack_from(fmt,md,dataOff+di)[0] if di>=0 else None
        else: vals[name]=None
    return dict(base=base,values=vals)
tables={}; enums={}; structs={}
KIND={}
for td in TD.values():
    if td['ns']!='MetalFury.FBTypes': continue
    for q in range(td['fcount']):
        nm,ti,_=struct.unpack_from('<3I',md,fOff+(td['fieldStart']+q)*12)
        if cstr(nm)=='__p':
            k=il2type(ti)
            if k[0] in ('class','valuetype') and k[1] in ('Table','Struct'): KIND[td['name']]='table' if k[1]=='Table' else 'struct'
for td in TD.values():
    if td['ns']!='MetalFury.FBTypes': continue
    parent=il2type(td['parent']) if td['parent']!=0xFFFFFFFF else ('other','')
    ptype=None
    for q in range(td['fcount']):
        nm,ti,_=struct.unpack_from('<3I',md,fOff+(td['fieldStart']+q)*12)
        if cstr(nm)=='__p':
            k=il2type(ti); ptype=k[1] if k[0] in ('class','valuetype') else None
    if ptype in ('Table','Struct'):
        parent=('class',ptype)
        fields=[]; seen={}
        for k in range(td['mcount']):
            m=struct.unpack_from('<11I4H',md,mOff+(td['methodStart']+k)*52); name=cstr(m[0]); pc=m[14]; generic=m[4]!=0xFFFFFFFF
            if name in ('get_ByteBuffer',) or name.startswith(('Get','Create','Start','Add','End','Mutate','__','Validate','Pack','UnPack','.')): continue
            if name.startswith('get_') and pc==0 and not name.endswith('Length'):
                fn=name[4:]; k2=il2type(m[2])
                if fn in seen: continue
                if k2[0]=='valuetype' and k2[2]['ns']=='MetalFury.FBTypes' and k2[1].endswith('Union'):
                    seen[fn]=len(fields); fields.append(dict(name=fn,kind='union_type',type=k2[1])); continue
                if k2[0]=='scalar': seen[fn]=len(fields); fields.append(dict(name=fn,kind='scalar',type=k2[1]))
                elif k2[0]=='string': seen[fn]=len(fields); fields.append(dict(name=fn,kind='string'))
                elif k2[0]=='class': seen[fn]=len(fields); fields.append(dict(name=fn,kind='table',type=k2[1]))
                elif k2[0]=='valuetype':
                    sub=k2[2]
                    if any(cstr(struct.unpack_from('<I',md,fOff+(sub['fieldStart']+q)*12)[0])=='value__' for q in range(sub['fcount'])):
                        seen[fn]=len(fields); fields.append(dict(name=fn,kind='enum',type=k2[1]))
                    else: seen[fn]=len(fields); fields.append(dict(name=fn,kind=KIND.get(k2[1],'struct'),type=k2[1]))
                else: seen[fn]=len(fields); fields.append(dict(name=fn,kind='unknown',type=str(k2)))
            elif pc==1 and not generic and not name.startswith('get_'):
                # vector accessor X(int j)
                pn,pt,pty=struct.unpack_from('<3I',md,pOff+m[3]*12)
                if il2type(pty)[:2]!=('scalar','int'): continue
                if name in seen: continue
                k2=il2type(m[2]); seen[name]=len(fields)
                if k2[0]=='scalar': fields.append(dict(name=name,kind='vector',elem='scalar',type=k2[1]))
                elif k2[0]=='string': fields.append(dict(name=name,kind='vector',elem='string'))
                elif k2[0]=='class': fields.append(dict(name=name,kind='vector',elem='table',type=k2[1]))
                elif k2[0]=='valuetype': fields.append(dict(name=name,kind='vector',elem=KIND.get(k2[1],'struct'),type=k2[1]))
            elif generic and pc==0 and not name.startswith('get_'):
                # union value accessor T Data<T>()
                if name in seen: continue
                seen[name]=len(fields); fields.append(dict(name=name,kind='union',type=None))
        # link union value fields to their type field (NameType)
        for fl in fields:
            if fl['kind']=='union':
                tf=next((f for f in fields if f['kind']=='union_type' and f['name']==fl['name']+'Type'),None)
                fl['type']=tf['type'] if tf else None
        (tables if parent[1]=='Table' else structs)[td['name']]=dict(fields=fields)
    elif parent[0]=='class' and parent[1]=='Enum':
        enums[td['name']]=enum_def(td)
# alias de uniones: clases *UnionUnion del object API tienen metodos As<Miembro>() cuyo tipo de retorno es la tabla real
unions={}
for td in TD.values():
    if td['ns']!='MetalFury.FBTypes' or not td['name'].endswith('UnionUnion'): continue
    uname=td['name'][:-5]; m_={}
    for k in range(td['mcount']):
        m=struct.unpack_from('<11I4H',md,mOff+(td['methodStart']+k)*52); name=cstr(m[0])
        if name.startswith('As') and m[14]==0:
            k2=il2type(m[2]); tn=k2[1] if k2[0] in ('class','valuetype') else None
            if tn and tn.endswith('T'): tn=tn[:-1]
            m_[name[2:]]=tn
    unions[uname]=m_
json.dump(dict(tables=tables,structs=structs,enums=enums,unions=unions),open(OUT,'w'),indent=1)
print('unions:',{k:len(v) for k,v in unions.items()}); print('alias ej:',{k:v for k,v in unions['GameSvrRspUnion'].items() if k!=v})
print('tables',len(tables),'structs',len(structs),'enums',len(enums))
print('ej RelayServerInfo:',tables['RelayServerInfo'])
print('ej GameSvrRsp:',tables['GameSvrRsp'])
print('ej LoginGameSvrRsp:',tables['LoginGameSvrRsp'])
print('enum GameSvrRspUnion (primeros):',list(enums['GameSvrRspUnion']['values'].items())[:5], enums['GameSvrRspUnion']['base'])
print('enum NetCode:',enums.get('NetCode'))
print('structs:',list(structs)[:10])
