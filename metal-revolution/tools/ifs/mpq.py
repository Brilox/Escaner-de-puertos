import struct
def _crypt_table():
    t=[0]*0x500; seed=0x00100001
    for i in range(0x100):
        j=i
        for _ in range(5):
            seed=(seed*125+3)%0x2AAAAB; a=(seed&0xFFFF)<<16
            seed=(seed*125+3)%0x2AAAAB; b=seed&0xFFFF
            t[j]=a|b; j+=0x100
    return t
CT=_crypt_table()
def hash_str(s, typ):
    s1=0x7FED7FED; s2=0xEEEEEEEE
    for ch in s.upper().encode():
        v=CT[(typ<<8)+ch]; s1=(v^(s1+s2))&0xFFFFFFFF; s2=(ch+s1+s2+(s2<<5)+3)&0xFFFFFFFF
    return s1
def decrypt(data,key):
    n=len(data)//4; w=list(struct.unpack('<%dI'%n,data[:n*4])); s2=0xEEEEEEEE; out=[]
    for x in w:
        s2=(s2+CT[0x400+(key&0xFF)])&0xFFFFFFFF; y=(x^((key+s2)&0xFFFFFFFF))&0xFFFFFFFF; out.append(y)
        key=((((~key)<<0x15)+0x11111111)|(key>>0x0B))&0xFFFFFFFF; s2=(y+s2+(s2<<5)+3)&0xFFFFFFFF
    return struct.pack('<%dI'%n,*out)+data[n*4:]
