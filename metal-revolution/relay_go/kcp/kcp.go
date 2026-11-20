// Package kcp: KCP minimo (ARQ sobre UDP) compatible con el del juego, traduccion directa de server/relay.py:
// nodelay, intervalo 10 ms, reenvio rapido a los 2 ACK saltados, sin control de congestion, ventanas de 128.
package kcp

import "encoding/binary"

const (
	CmdPush  = 81
	CmdAck   = 82
	CmdWask  = 83
	CmdWins  = 84
	Cabecera = 24
	MTU      = 1200
)

type seg struct {
	sn, rto, resendts, fastack, xmit uint32
	frg                              uint8
	datos                            []byte
}

type recibido struct {
	frg   uint8
	datos []byte
}

type KCP struct {
	Conv                   uint32
	salida                 func([]byte)
	sndUna, sndNxt, rcvNxt uint32
	sndWnd, rcvWnd, rmtWnd uint32
	mss                    int
	colaEnvio              []*seg
	sinConfirmar           []*seg
	fueraDeOrden           map[uint32]recibido
	colaRecibo             []recibido
	acks                   [][2]uint32
	srtt, rttvar           int64
	rto, rtoMin            uint32
	reenvioRapido          uint32
	responderVentana       bool
	sigSondeo              uint32
	Muerto                 bool
	Reenvios               int
	out                    []byte
}

func New(conv uint32, salida func([]byte)) *KCP {
	return &KCP{Conv: conv, salida: salida, sndWnd: 128, rcvWnd: 128, rmtWnd: 128, mss: MTU - Cabecera,
		fueraDeOrden: map[uint32]recibido{}, rto: 100, rtoMin: 30, reenvioRapido: 2, out: make([]byte, 0, MTU)}
}

func (k *KCP) SndNxt() uint32 { return k.sndNxt }
func (k *KCP) RcvNxt() uint32 { return k.rcvNxt }

// Input procesa un datagrama KCP. Devuelve false si no es valido.
func (k *KCP) Input(data []byte, ahora uint32) bool {
	pos, n := 0, len(data)
	var maxack uint32
	hayAck := false
	for n-pos >= Cabecera {
		conv := binary.LittleEndian.Uint32(data[pos:])
		cmd := data[pos+4]
		frg := data[pos+5]
		wnd := uint32(binary.LittleEndian.Uint16(data[pos+6:]))
		ts := binary.LittleEndian.Uint32(data[pos+8:])
		sn := binary.LittleEndian.Uint32(data[pos+12:])
		una := binary.LittleEndian.Uint32(data[pos+16:])
		ln := int(binary.LittleEndian.Uint32(data[pos+20:]))
		pos += Cabecera
		if conv != k.Conv || cmd < CmdPush || cmd > CmdWins || n-pos < ln {
			return false
		}
		k.rmtWnd = wnd
		for len(k.sinConfirmar) > 0 && k.sinConfirmar[0].sn < una {
			k.sinConfirmar = k.sinConfirmar[1:]
		}
		switch cmd {
		case CmdAck:
			rtt := ahora - ts
			if rtt < 60000 {
				k.medirRTT(int64(rtt))
			}
			for i, s := range k.sinConfirmar {
				if s.sn == sn {
					k.sinConfirmar = append(k.sinConfirmar[:i], k.sinConfirmar[i+1:]...)
					break
				}
				if s.sn > sn {
					break
				}
			}
			if !hayAck || sn > maxack {
				maxack, hayAck = sn, true
			}
		case CmdPush:
			if sn < k.rcvNxt+k.rcvWnd {
				k.acks = append(k.acks, [2]uint32{sn, ts})
				if _, ya := k.fueraDeOrden[sn]; sn >= k.rcvNxt && !ya {
					d := make([]byte, ln)
					copy(d, data[pos:pos+ln])
					k.fueraDeOrden[sn] = recibido{frg, d}
					k.ordenar()
				}
			}
		case CmdWask:
			k.responderVentana = true
		}
		pos += ln
	}
	if len(k.sinConfirmar) > 0 {
		k.sndUna = k.sinConfirmar[0].sn
	} else {
		k.sndUna = k.sndNxt
	}
	if hayAck {
		for _, s := range k.sinConfirmar {
			if s.sn >= maxack {
				break
			}
			s.fastack++
		}
	}
	return true
}

func (k *KCP) ordenar() {
	for uint32(len(k.colaRecibo)) < k.rcvWnd {
		r, ok := k.fueraDeOrden[k.rcvNxt]
		if !ok {
			break
		}
		delete(k.fueraDeOrden, k.rcvNxt)
		k.colaRecibo = append(k.colaRecibo, r)
		k.rcvNxt++
	}
}

func (k *KCP) medirRTT(rtt int64) {
	if k.srtt == 0 {
		k.srtt, k.rttvar = rtt, rtt/2
	} else {
		d := rtt - k.srtt
		if d < 0 {
			d = -d
		}
		k.rttvar = (3*k.rttvar + d) / 4
		k.srtt = (7*k.srtt + rtt) / 8
		if k.srtt < 1 {
			k.srtt = 1
		}
	}
	v := 4 * k.rttvar
	if v < 10 {
		v = 10
	}
	r := k.srtt + v
	if r < int64(k.rtoMin) {
		r = int64(k.rtoMin)
	}
	if r > 5000 {
		r = 5000
	}
	k.rto = uint32(r)
}

// Recv devuelve el siguiente mensaje completo o nil.
func (k *KCP) Recv() []byte {
	n := 0
	completo := false
	for _, r := range k.colaRecibo {
		n++
		if r.frg == 0 {
			completo = true
			break
		}
	}
	if !completo {
		return nil
	}
	var msg []byte
	if n == 1 {
		msg = k.colaRecibo[0].datos
	} else {
		for _, r := range k.colaRecibo[:n] {
			msg = append(msg, r.datos...)
		}
	}
	k.colaRecibo = k.colaRecibo[n:]
	k.ordenar()
	return msg
}

func (k *KCP) Send(datos []byte) {
	if len(datos) == 0 {
		k.colaEnvio = append(k.colaEnvio, &seg{datos: []byte{}})
		return
	}
	nt := (len(datos) + k.mss - 1) / k.mss
	for i := 0; i < nt; i++ {
		fin := (i + 1) * k.mss
		if fin > len(datos) {
			fin = len(datos)
		}
		d := make([]byte, fin-i*k.mss)
		copy(d, datos[i*k.mss:fin])
		k.colaEnvio = append(k.colaEnvio, &seg{frg: uint8(nt - 1 - i), datos: d})
	}
}

func (k *KCP) Pendiente() bool {
	return len(k.acks) > 0 || len(k.colaEnvio) > 0 || len(k.sinConfirmar) > 0 || k.responderVentana
}

func (k *KCP) emitir(cmd uint8, frg uint8, wnd uint32, ts, sn, una uint32, datos []byte) {
	if len(k.out)+Cabecera+len(datos) > MTU && len(k.out) > 0 {
		k.salida(k.out)
		k.out = make([]byte, 0, MTU)
	}
	var h [Cabecera]byte
	binary.LittleEndian.PutUint32(h[0:], k.Conv)
	h[4], h[5] = cmd, frg
	binary.LittleEndian.PutUint16(h[6:], uint16(wnd))
	binary.LittleEndian.PutUint32(h[8:], ts)
	binary.LittleEndian.PutUint32(h[12:], sn)
	binary.LittleEndian.PutUint32(h[16:], una)
	binary.LittleEndian.PutUint32(h[20:], uint32(len(datos)))
	k.out = append(k.out, h[:]...)
	k.out = append(k.out, datos...)
}

func (k *KCP) Flush(ahora uint32) {
	wnd := uint32(0)
	if uint32(len(k.colaRecibo)) < k.rcvWnd {
		wnd = k.rcvWnd - uint32(len(k.colaRecibo))
	}
	una := k.rcvNxt
	for _, a := range k.acks {
		k.emitir(CmdAck, 0, wnd, a[1], a[0], una, nil)
	}
	k.acks = k.acks[:0]
	if k.rmtWnd == 0 && ahora >= k.sigSondeo {
		k.emitir(CmdWask, 0, wnd, 0, 0, una, nil)
		k.sigSondeo = ahora + 1000
	}
	if k.responderVentana {
		k.emitir(CmdWins, 0, wnd, 0, 0, una, nil)
		k.responderVentana = false
	}
	v := k.sndWnd
	if k.rmtWnd < v {
		v = k.rmtWnd
	}
	if v < 1 {
		v = 1
	}
	tope := k.sndUna + v
	for len(k.colaEnvio) > 0 && k.sndNxt < tope {
		s := k.colaEnvio[0]
		k.colaEnvio = k.colaEnvio[1:]
		s.sn = k.sndNxt
		k.sndNxt++
		k.sinConfirmar = append(k.sinConfirmar, s)
	}
	for _, s := range k.sinConfirmar {
		switch {
		case s.xmit == 0:
			s.rto = k.rto
			s.resendts = ahora + s.rto
		case ahora >= s.resendts:
			m := s.rto
			if k.rto > m {
				m = k.rto
			}
			s.rto += m / 2
			s.resendts = ahora + s.rto
			k.Reenvios++
		case s.fastack >= k.reenvioRapido:
			s.resendts = ahora + s.rto
			k.Reenvios++
		default:
			continue
		}
		s.xmit++
		s.fastack = 0
		if s.xmit > 40 {
			k.Muerto = true
		}
		k.emitir(CmdPush, s.frg, wnd, ahora, s.sn, una, s.datos)
	}
	if len(k.out) > 0 {
		k.salida(k.out)
		k.out = make([]byte, 0, MTU)
	}
}
