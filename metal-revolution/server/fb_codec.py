#!/usr/bin/env python3
"""Codificador/decodificador FlatBuffers generico guiado por el esquema extraido (esquema_fb.json).
decode(schema, table, buf) -> dict ; encode(schema, table, dict) -> bytes (con flatbuffers.Builder)."""
import struct, json
SC={'bool':('<?',1),'byte':('<b',1),'ubyte':('<B',1),'short':('<h',2),'ushort':('<H',2),'int':('<i',4),'uint':('<I',4),'long':('<q',8),'ulong':('<Q',8),'float':('<f',4),'double':('<d',8),'char':('<H',2)}
class Codec:
    def __init__(self, schema):
        self.S=schema; self.T=schema['tables']; self.ST=schema['structs']; self.E=schema['enums']; self.U=schema.get('unions',{})
        self.struct_layout={}
        self.enum_by_value={n:{v:k for k,v in e['values'].items()} for n,e in self.E.items()}
        # Listas de enums (p. ej. RoundResult en UploadBattleResult) viajan como listas de numeros simples.
        for t in list(self.T.values()) + list(self.ST.values()):
            for f in t['fields']:
                if f['kind'] == 'vector' and f.get('elem') == 'struct' and f.get('type') in self.E and f['type'] not in self.ST:
                    f['elem'] = 'scalar'; f['type'] = self.E[f['type']]['base']
    def union_table(self,uname,value):
        name=self.enum_by_value[uname].get(value); 
        if name is None: return None,None
        return name, self.U.get(uname,{}).get(name,name)
    def enum_base(self,name): return self.E[name]['base'] if name in self.E else 'int'
    # ---------- structs (inline) ----------
    def layout(self,name):
        if name in self.struct_layout: return self.struct_layout[name]
        off=0; maxal=1; items=[]
        for f in self.ST[name]['fields']:
            if f['kind']=='scalar': fmt,sz=SC[f['type']]; al=sz
            elif f['kind']=='enum': fmt,sz=SC[self.enum_base(f['type'])]; al=sz
            elif f['kind']=='struct': sz,al=self.layout(f['type'])[1:3]; fmt=None
            else: raise ValueError('struct field '+str(f))
            off=(off+al-1)//al*al; items.append((f,off,fmt,sz)); off+=sz; maxal=max(maxal,al)
        size=(off+maxal-1)//maxal*maxal
        self.struct_layout[name]=(items,size,maxal); return self.struct_layout[name]
    def dec_struct(self,name,buf,pos):
        items,size,_=self.layout(name); out={}
        for f,o,fmt,sz in items:
            out[f['name']]=struct.unpack_from(fmt,buf,pos+o)[0] if fmt else self.dec_struct(f['type'],buf,pos+o)
        return out
    # ---------- decode ----------
    def decode(self,table,buf,pos=None):
        if pos is None: pos=struct.unpack_from('<I',buf,0)[0]
        vt=pos-struct.unpack_from('<i',buf,pos)[0]; vsize,tsize=struct.unpack_from('<HH',buf,vt)
        out={}; fields=self.T[table]['fields']
        def fo(i):
            o=4+2*i
            return struct.unpack_from('<H',buf,vt+o)[0] if o+2<=vsize else 0
        for i,f in enumerate(fields):
            off=fo(f.get('id',i))
            if not off:
                if f['kind']=='scalar': out[f['name']]=f.get('default', False if f['type']=='bool' else 0)
                elif f['kind']=='enum': out[f['name']]=f.get('default',0)
                continue
            p=pos+off; k=f['kind']
            if k=='scalar': out[f['name']]=struct.unpack_from(SC[f['type']][0],buf,p)[0]
            elif k in('enum','union_type'): out[f['name']]=struct.unpack_from(SC[self.enum_base(f['type'])][0],buf,p)[0]
            elif k=='string': q=p+struct.unpack_from('<I',buf,p)[0]; n=struct.unpack_from('<I',buf,q)[0]; out[f['name']]=buf[q+4:q+4+n].decode('utf-8','replace')
            elif k=='table': out[f['name']]=self.decode(f['type'],buf,p+struct.unpack_from('<I',buf,p)[0])
            elif k=='struct': out[f['name']]=self.dec_struct(f['type'],buf,p)
            elif k=='union':
                tv=out.get(f['name']+'Type',0); mname,tname=self.union_table(f['type'],tv)
                out[f['name']]=self.decode(tname,buf,p+struct.unpack_from('<I',buf,p)[0]) if tname in self.T else None
                out[f['name']+'Type']=mname
            elif k=='vector':
                q=p+struct.unpack_from('<I',buf,p)[0]; n=struct.unpack_from('<I',buf,q)[0]; q+=4; arr=[]
                for j in range(n):
                    if f['elem']=='scalar': fmt,sz=SC[f['type']]; arr.append(struct.unpack_from(fmt,buf,q)[0]); q+=sz
                    elif f['elem']=='string': r=q+struct.unpack_from('<I',buf,q)[0]; m=struct.unpack_from('<I',buf,r)[0]; arr.append(buf[r+4:r+4+m].decode('utf-8','replace')); q+=4
                    elif f['elem']=='table': arr.append(self.decode(f['type'],buf,q+struct.unpack_from('<I',buf,q)[0])); q+=4
                    elif f['elem']=='struct': arr.append(self.dec_struct(f['type'],buf,q)); q+=self.layout(f['type'])[1]
                out[f['name']]=arr
        return out
    # ---------- encode ----------
    def encode(self,table,obj):
        import flatbuffers
        b=flatbuffers.Builder(1024); b.forceDefaults=True; root=self.enc_table(b,table,obj); b.Finish(root); return bytes(b.Output())
    def enc_struct(self,b,name,obj):
        items,size,al=self.layout(name); b.Prep(al,size)
        for f,o,fmt,sz in reversed(items):
            pad=0
            # write fields in reverse with explicit padding: compute end positions
        # simpler: build bytes manually then push
        raw=bytearray(size)
        def fill(nm,o_base,ob):
            for f,o,fmt,sz in self.layout(nm)[0]:
                v=ob.get(f['name'],0)
                if fmt: struct.pack_into(fmt,raw,o_base+o,v)
                else: fill(f['type'],o_base+o,v or {})
        fill(name,0,obj or {})
        b.head=b.head-size; b.Bytes[b.head:b.head+size]=raw
        return b.Offset()
    def enc_table(self,b,table,obj):
        fields=self.T[table]['fields']; offs={}
        for f in fields:   # children first
            v=obj.get(f['name']); k=f['kind']
            if v is None: continue
            if k=='string': offs[f['name']]=b.CreateString(v)
            elif k=='table': offs[f['name']]=self.enc_table(b,f['type'],v)
            elif k=='union':
                tname=obj.get(f['name']+'Type')
                if isinstance(tname,int): tname=self.enum_by_value[f['type']][tname]
                offs[f['name']]=self.enc_table(b,self.U.get(f['type'],{}).get(tname,tname),v)
            elif k=='vector':
                if f['elem']=='scalar':
                    fmt,sz=SC[f['type']]; b.StartVector(sz,len(v),sz)
                    for x in reversed(v): b.Prep(sz,0); b.head-=sz; struct.pack_into(fmt,b.Bytes,b.head,x)
                    offs[f['name']]=b.EndVector()
                elif f['elem']=='string':
                    so=[b.CreateString(x) for x in v]; b.StartVector(4,len(so),4)
                    for x in reversed(so): b.PrependUOffsetTRelative(x)
                    offs[f['name']]=b.EndVector()
                elif f['elem']=='table':
                    so=[self.enc_table(b,f['type'],x) for x in v]; b.StartVector(4,len(so),4)
                    for x in reversed(so): b.PrependUOffsetTRelative(x)
                    offs[f['name']]=b.EndVector()
                elif f['elem']=='struct':
                    items,size,al=self.layout(f['type']); b.StartVector(size,len(v),al)
                    for x in reversed(v): self.enc_struct(b,f['type'],x)
                    offs[f['name']]=b.EndVector()
        b.StartObject(max([f.get('id',n) for n,f in enumerate(fields)],default=-1)+1)
        for n,f in enumerate(fields):
            i=f.get('id',n); v=obj.get(f['name']); k=f['kind']
            if k=='union': 
                if f['name'] in offs: b.PrependUOffsetTRelativeSlot(i,offs[f['name']],0)
                continue
            if v is None and f['name'] not in offs: continue
            if k=='scalar': self.slot(b,i,f['type'],v)
            elif k=='enum': 
                if isinstance(v,str): v=self.E[f['type']]['values'][v]
                self.slot(b,i,self.enum_base(f['type']),v)
            elif k=='union_type':
                if isinstance(v,str): v=self.E[f['type']]['values'][v]
                self.slot(b,i,self.enum_base(f['type']),v)
            elif k in('string','table','vector'): b.PrependUOffsetTRelativeSlot(i,offs[f['name']],0)
            elif k=='struct': b.Prep(self.layout(f['type'])[2],self.layout(f['type'])[1]); self.enc_struct(b,f['type'],v); b.Slot(i)
        return b.EndObject()
    def slot(self,b,i,t,v):
        fmt,sz=SC[t]
        {'bool':b.PrependBoolSlot,'byte':b.PrependInt8Slot,'ubyte':b.PrependUint8Slot,'short':b.PrependInt16Slot,'ushort':b.PrependUint16Slot,'int':b.PrependInt32Slot,'uint':b.PrependUint32Slot,'long':b.PrependInt64Slot,'ulong':b.PrependUint64Slot,'float':b.PrependFloat32Slot,'double':b.PrependFloat64Slot,'char':b.PrependUint16Slot}[t](i,v,0)
