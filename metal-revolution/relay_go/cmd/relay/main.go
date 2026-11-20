// relay_go: relay UDP de las peleas de Metal Online, traduccion a Go de server/relay.py (mismo protocolo).
//
// Lo arranca mr_server.py como proceso aparte. Control por la entrada/salida estandar, una linea JSON por mensaje:
//
//	entrada (del servidor):  {"t":"esperados","id":123,"n":2}   cuantos telefonos deben entrar a la pelea 123
//	                         {"t":"fin","id":123}               la pelea 123 se cerro
//	salida (al servidor):    {"t":"empezo","id":123}             entraron todos: empieza la pelea
//	                         {"t":"red", ...}                   resumen de red de una pelea terminada
//
// Los mensajes de registro van por la salida de error (el servidor los copia a mr_server.log).
package main

import (
	"bufio"
	"encoding/binary"
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"net"
	"os"
	"sync"
	"time"

	"metalonline/relay/kcp"
)

var tam = map[byte]int{0: 11, 1: 1, 2: 1, 14: 7, 15: 7, 16: 7, 17: 9, 18: 17} // tamano de cada mensaje cliente -> servidor

const inactivo = 20 * time.Second

var inicioReloj = time.Now()

func ms() uint32 { return uint32(time.Since(inicioReloj).Milliseconds()) }

type par struct {
	addr                *net.UDPAddr
	clave               string
	k                   *kcp.KCP
	sala                *sala
	lado, pos           byte
	sub                 uint16
	esperando           bool
	ultimo              time.Time
	rapido              []byte
	recibidos, enviados int
	pingMin, pingMax    int
	pingSuma, pingN     int
}

type sala struct {
	id       int32
	pares    map[string]*par
	completa bool
	inputs   int
	inicio   time.Time
}

type paquete struct {
	datos []byte
	addr  *net.UDPAddr
	ping  bool
}

type relay struct {
	sock, sockPing *net.UDPConn
	pares          map[string]*par
	salas          map[int32]*sala
	esperados      map[int32]int
	sucios         map[*par]bool
	pings, raros   int
	salida         *json.Encoder
	muSalida       sync.Mutex
}

func (r *relay) evento(v map[string]interface{}) {
	r.muSalida.Lock()
	defer r.muSalida.Unlock()
	r.salida.Encode(v)
}

func (r *relay) enviarUDP(b []byte, a *net.UDPAddr) { r.sock.WriteToUDP(b, a) }

func (r *relay) nuevoPar(a *net.UDPAddr, conv uint32) *par {
	p := &par{addr: a, clave: a.String(), ultimo: time.Now(), pingMin: -1}
	dst := a
	p.k = kcp.New(conv, func(b []byte) { r.enviarUDP(b, dst) })
	r.pares[p.clave] = p
	return p
}

func (r *relay) datagrama(d []byte, a *net.UDPAddr, enPing bool) {
	if len(d) >= 6 && d[0] == 0 && d[1] == 1 { // ping TLV previo a la conexion
		r.pings++
		if r.pings <= 5 || r.pings%500 == 0 {
			log.Printf("relay: ping UDP de %s (%d en total)", a, r.pings)
		}
		resp := append([]byte{0, 2}, d[2:]...)
		if enPing && r.sockPing != nil {
			r.sockPing.WriteToUDP(resp, a)
		} else {
			r.sock.WriteToUDP(resp, a)
		}
		return
	}
	if enPing {
		r.raros++
		if r.raros <= 10 {
			log.Printf("relay: datagrama desconocido en el puerto del ping de %s", a)
		}
		return
	}
	if len(d) < 5 {
		return
	}
	clave := a.String()
	p := r.pares[clave]
	if d[0] == 0 && d[1] == 0 && d[2] == 0 && d[3] == 0 { // canal rapido, sin KCP
		if p == nil {
			p = r.nuevoPar(a, 6666)
			log.Printf("relay: nuevo telefono %s (canal rapido)", a)
		}
		p.ultimo = time.Now()
		r.mensajes(p, d[4:], false)
	} else {
		conv := binary.LittleEndian.Uint32(d)
		if p == nil || (p.k.Conv != conv && p.k.SndNxt() == 0 && p.k.RcvNxt() == 0) {
			if len(d) < kcp.Cabecera || d[4] < kcp.CmdPush || d[4] > kcp.CmdWins {
				r.raros++
				if r.raros <= 10 {
					log.Printf("relay: datagrama desconocido de %s: %x", a, d[:min(48, len(d))])
				}
				return
			}
			viejo := p
			p = r.nuevoPar(a, conv)
			if viejo != nil && viejo.sala != nil {
				r.quitar(viejo, false)
			}
			log.Printf("relay: nuevo telefono %s (KCP conv=%d)", a, conv)
		}
		p.ultimo = time.Now()
		if !p.k.Input(d, ms()) {
			r.raros++
			if r.raros <= 10 {
				log.Printf("relay: KCP invalido de %s", a)
			}
			return
		}
		for {
			m := p.k.Recv()
			if m == nil {
				break
			}
			r.mensajes(p, m, true)
		}
		r.sucios[p] = true
	}
	r.vaciar()
}

func (r *relay) vaciar() {
	ahora := ms()
	for p := range r.sucios {
		if len(p.rapido) > 0 {
			r.enviarUDP(append([]byte{0, 0, 0, 0}, p.rapido...), p.addr)
			p.rapido = p.rapido[:0]
		}
		p.k.Flush(ahora)
		delete(r.sucios, p)
	}
}

func (r *relay) tick() {
	ahora := ms()
	for _, p := range r.pares {
		if p.k.Pendiente() {
			p.k.Flush(ahora)
		}
	}
}

func (r *relay) limpiar() {
	t := time.Now()
	for _, p := range r.pares {
		if t.Sub(p.ultimo) > inactivo || p.k.Muerto {
			log.Printf("relay: %s sin respuesta, se retira", p.addr)
			r.quitar(p, true)
		}
	}
}

func (r *relay) enviar(p *par, d []byte, fiable bool) {
	if fiable {
		p.k.Send(d)
	} else {
		p.rapido = append(p.rapido, d...)
	}
	p.enviados++
	r.sucios[p] = true
}

func (r *relay) mensajes(p *par, buf []byte, fiable bool) {
	i, n := 0, len(buf)
	for i < n {
		t := buf[i]
		tm, ok := tam[t]
		if !ok || i+tm > n {
			r.raros++
			if r.raros <= 20 {
				log.Printf("relay: mensaje desconocido tipo=%d de %s", t, p.addr)
			}
			return
		}
		m := buf[i : i+tm]
		i += tm
		p.recibidos++
		switch {
		case t == 0:
			r.entrar(p, m)
		case t == 1:
			r.salir(p)
		case t == 2:
		case p.sala != nil:
			if t == 14 {
				p.sala.inputs++
			}
			if t == 15 { // SyncPing: el telefono informa su ping (ms) -> estadistica de red de la pelea
				ping := int(binary.LittleEndian.Uint16(m[5:]))
				if ping > 0 && ping < 5000 {
					p.pingN++
					p.pingSuma += ping
					if p.pingMin < 0 || ping < p.pingMin {
						p.pingMin = ping
					}
					if ping > p.pingMax {
						p.pingMax = ping
					}
				}
			}
			rsp := make([]byte, 0, tm+2)
			rsp = append(rsp, m[:5]...)
			rsp = append(rsp, p.lado, p.pos)
			rsp = append(rsp, m[5:]...)
			for _, otro := range p.sala.pares {
				if otro != p {
					r.enviar(otro, rsp, fiable)
				}
			}
		}
	}
}

func (r *relay) entrar(p *par, m []byte) {
	mid := int32(binary.LittleEndian.Uint32(m[1:]))
	sub := binary.LittleEndian.Uint16(m[5:])
	lado, pos, reentra := m[7], m[8], m[9]
	s := r.salas[mid]
	if s == nil {
		s = &sala{id: mid, pares: map[string]*par{}}
		r.salas[mid] = s
	}
	for _, otro := range s.pares { // el mismo jugador desde otra conexion: la vieja sobra
		if otro != p && otro.lado == lado && otro.pos == pos {
			r.quitar(otro, true)
		}
	}
	if p.sala != nil && p.sala != s {
		r.quitar(p, false)
	}
	p.sala, p.lado, p.pos, p.sub, p.esperando = s, lado, pos, sub, true
	s.pares[p.clave] = p
	esperados := r.esperados[mid]
	if esperados == 0 {
		esperados = 2
	}
	listos := 0
	for _, o := range s.pares {
		if o.esperando {
			listos++
		}
	}
	extra := ""
	if reentra != 0 {
		extra = " [reconexion]"
	}
	log.Printf("relay: pelea %d: entra lado=%d pos=%d desde %s (%d de %d)%s", mid, lado, pos, p.addr, listos, esperados, extra)
	if reentra != 0 && s.completa {
		p.esperando = false
		r.enviar(p, []byte{0}, true)
		return
	}
	if listos >= esperados && listos == len(s.pares) {
		s.completa, s.inputs, s.inicio = true, 0, time.Now()
		for _, o := range s.pares {
			o.esperando = false
			r.enviar(o, []byte{0}, true)
		}
		log.Printf("relay: pelea %d: estan todos, EMPIEZA LA PELEA", mid)
		r.evento(map[string]interface{}{"t": "empezo", "id": mid})
	}
}

func (r *relay) salir(p *par) {
	if p.sala != nil {
		log.Printf("relay: pelea %d: sale lado=%d pos=%d (recibidos=%d enviados=%d reenvios=%d)", p.sala.id, p.lado, p.pos, p.recibidos, p.enviados, p.k.Reenvios)
	}
	r.quitar(p, false)
}

func (r *relay) quitar(p *par, borrar bool) {
	if s := p.sala; s != nil {
		r.resumenRed(p)
		if s.pares[p.clave] == p {
			delete(s.pares, p.clave)
		}
		p.sala, p.esperando = nil, false
		if len(s.pares) == 0 {
			if s.completa {
				log.Printf("relay: pelea %d terminada: %d inputs reenviados en %.0f s", s.id, s.inputs, time.Since(s.inicio).Seconds())
			}
			delete(r.salas, s.id)
		}
	}
	if borrar && r.pares[p.clave] == p {
		delete(r.pares, p.clave)
	}
	delete(r.sucios, p)
}

// resumenRed manda al servidor los datos de red de un jugador al dejar la pelea (para el registro de la prueba).
func (r *relay) resumenRed(p *par) {
	if p.sala == nil || !p.sala.completa {
		return
	}
	prom := 0
	if p.pingN > 0 {
		prom = p.pingSuma / p.pingN
	}
	r.evento(map[string]interface{}{"t": "red", "id": p.sala.id, "lado": p.lado, "pos": p.pos, "ip": p.addr.IP.String(),
		"ping_prom": prom, "ping_min": p.pingMin, "ping_max": p.pingMax, "muestras": p.pingN,
		"recibidos": p.recibidos, "enviados": p.enviados, "reenvios": p.k.Reenvios, "segundos": int(time.Since(p.sala.inicio).Seconds())})
}

func abrir(escucha string, puerto int) *net.UDPConn {
	c, err := net.ListenUDP("udp4", &net.UDPAddr{IP: net.ParseIP(escucha), Port: puerto})
	if err != nil {
		log.Fatalf("no puedo abrir el puerto UDP %d: %v", puerto, err)
	}
	c.SetReadBuffer(1 << 20)
	c.SetWriteBuffer(1 << 20)
	return c
}

func leer(c *net.UDPConn, ping bool, ch chan<- paquete) {
	buf := make([]byte, 4096)
	for {
		n, a, err := c.ReadFromUDP(buf)
		if err != nil {
			if ne, ok := err.(net.Error); ok && !ne.Timeout() && isClosed(err) {
				return
			}
			continue // en Windows un envio a un puerto cerrado aparece como error de lectura: se ignora
		}
		d := make([]byte, n)
		copy(d, buf[:n])
		ch <- paquete{d, a, ping}
	}
}

func isClosed(err error) bool {
	return err != nil && (err == net.ErrClosed || containsClosed(err.Error()))
}

func containsClosed(s string) bool {
	for i := 0; i+len("use of closed") <= len(s); i++ {
		if s[i:i+len("use of closed")] == "use of closed" {
			return true
		}
	}
	return false
}

func main() {
	escucha := flag.String("escucha", "0.0.0.0", "direccion donde escuchar")
	puerto := flag.Int("puerto", 8080, "puerto UDP de la pelea")
	puertoPing := flag.Int("puerto-ping", -1, "puerto UDP del ping previo (por defecto puerto-1; 0 = ninguno)")
	flag.Parse()
	log.SetFlags(0)
	log.SetOutput(os.Stderr)
	r := &relay{pares: map[string]*par{}, salas: map[int32]*sala{}, esperados: map[int32]int{}, sucios: map[*par]bool{},
		salida: json.NewEncoder(os.Stdout)}
	r.sock = abrir(*escucha, *puerto)
	pp := *puertoPing
	if pp < 0 {
		pp = *puerto - 1
	}
	if pp > 0 && pp != *puerto {
		r.sockPing = abrir(*escucha, pp)
	}
	paquetes := make(chan paquete, 4096)
	go leer(r.sock, false, paquetes)
	if r.sockPing != nil {
		go leer(r.sockPing, true, paquetes)
	}
	control := make(chan map[string]interface{}, 256)
	go func() {
		sc := bufio.NewScanner(os.Stdin)
		for sc.Scan() {
			var m map[string]interface{}
			if json.Unmarshal(sc.Bytes(), &m) == nil {
				control <- m
			}
		}
		close(control) // el servidor se cerro: el relay tambien
	}()
	log.Printf("relay Go escuchando: pelea en el puerto %d, ping previo en el puerto %d", *puerto, pp)
	r.evento(map[string]interface{}{"t": "listo", "puerto": *puerto, "puerto_ping": pp})
	tick := time.NewTicker(10 * time.Millisecond)
	limpieza := time.NewTicker(2 * time.Second)
	for {
		select {
		case pq := <-paquetes:
			r.datagrama(pq.datos, pq.addr, pq.ping)
		case <-tick.C:
			r.tick()
		case <-limpieza.C:
			r.limpiar()
		case m, ok := <-control:
			if !ok {
				log.Printf("relay: el servidor se cerro, el relay termina")
				return
			}
			id := int32(num(m["id"]))
			switch m["t"] {
			case "esperados":
				r.esperados[id] = int(num(m["n"]))
			case "fin":
				delete(r.esperados, id)
			}
		}
	}
}

func num(v interface{}) float64 {
	if f, ok := v.(float64); ok {
		return f
	}
	return 0
}

var _ = fmt.Sprintf
