// carga: prueba de carga del relay. Simula N peleas (2 telefonos cada una) que mandan botones 60 veces por segundo
// por KCP, como el juego, y mide el retraso de cada input al pasar por el relay.
//
//	go run ./cmd/carga -relay 127.0.0.1:8080 -peleas 50 -segundos 10
package main

import (
	"encoding/binary"
	"flag"
	"fmt"
	"net"
	"sort"
	"sync"
	"sync/atomic"
	"time"

	"metalonline/relay/kcp"
)

var inicio = time.Now()

func ms() uint32 { return uint32(time.Since(inicio).Milliseconds()) }

type cliente struct {
	c      *net.UDPConn
	k      *kcp.KCP
	mu     sync.Mutex
	empezo atomic.Bool
	lat    []int
	recib  int
}

func nuevo(relay *net.UDPAddr, conv uint32) *cliente {
	c, err := net.DialUDP("udp4", nil, relay)
	if err != nil {
		panic(err)
	}
	c.SetReadBuffer(1 << 20)
	cl := &cliente{c: c}
	cl.k = kcp.New(conv, func(b []byte) { c.Write(b) })
	return cl
}

func (cl *cliente) leer(fin <-chan struct{}) {
	buf := make([]byte, 4096)
	for {
		select {
		case <-fin:
			return
		default:
		}
		cl.c.SetReadDeadline(time.Now().Add(100 * time.Millisecond))
		n, err := cl.c.Read(buf)
		if err != nil {
			continue
		}
		ahora := ms()
		cl.mu.Lock()
		cl.k.Input(buf[:n], ahora)
		for {
			m := cl.k.Recv()
			if m == nil {
				break
			}
			for i := 0; i < len(m); {
				switch m[i] {
				case 0:
					cl.empezo.Store(true)
					i++
				case 14: // input: frame (= ms de envio), lado, pos, botones
					env := binary.LittleEndian.Uint32(m[i+1:])
					cl.lat = append(cl.lat, int(ahora-env))
					cl.recib++
					i += 9
				default:
					i = len(m)
				}
			}
		}
		cl.k.Flush(ahora)
		cl.mu.Unlock()
	}
}

func main() {
	dir := flag.String("relay", "127.0.0.1:8080", "direccion del relay")
	peleas := flag.Int("peleas", 10, "peleas simultaneas")
	segundos := flag.Int("segundos", 10, "duracion de la medicion")
	flag.Parse()
	relay, _ := net.ResolveUDPAddr("udp4", *dir)
	fin := make(chan struct{})
	var todos []*cliente
	for p := 0; p < *peleas; p++ {
		for lado := 0; lado < 2; lado++ {
			cl := nuevo(relay, uint32(1000+p*2+lado))
			todos = append(todos, cl)
			go cl.leer(fin)
			m := make([]byte, 11)
			m[0] = 0
			binary.LittleEndian.PutUint32(m[1:], uint32(900000+p))
			m[7], m[8], m[10] = byte(lado), 0, 1
			cl.mu.Lock()
			cl.k.Send(m)
			cl.k.Flush(ms())
			cl.mu.Unlock()
		}
	}
	// esperar la salida de todas las peleas
	limite := time.Now().Add(10 * time.Second)
	for time.Now().Before(limite) {
		listos := 0
		for _, cl := range todos {
			if cl.empezo.Load() {
				listos++
			}
		}
		if listos == len(todos) {
			break
		}
		time.Sleep(20 * time.Millisecond)
	}
	// 60 inputs por segundo por telefono
	tick := time.NewTicker(time.Second / 60)
	fl := time.NewTicker(10 * time.Millisecond)
	t0 := time.Now()
	enviados := 0
	for time.Since(t0) < time.Duration(*segundos)*time.Second {
		select {
		case <-tick.C:
			ahora := ms()
			for _, cl := range todos {
				m := make([]byte, 7)
				m[0] = 14
				binary.LittleEndian.PutUint32(m[1:], ahora)
				cl.mu.Lock()
				cl.k.Send(m)
				cl.k.Flush(ahora)
				cl.mu.Unlock()
				enviados++
			}
		case <-fl.C:
			ahora := ms()
			for _, cl := range todos {
				cl.mu.Lock()
				cl.k.Flush(ahora)
				cl.mu.Unlock()
			}
		}
	}
	time.Sleep(500 * time.Millisecond)
	close(fin)
	var lat []int
	recib := 0
	for _, cl := range todos {
		cl.mu.Lock()
		lat = append(lat, cl.lat...)
		recib += cl.recib
		cl.mu.Unlock()
	}
	sort.Ints(lat)
	q := func(f float64) int {
		if len(lat) == 0 {
			return -1
		}
		return lat[int(f*float64(len(lat)-1))]
	}
	fmt.Printf("peleas=%d telefonos=%d enviados=%d recibidos=%d (%.1f%%) retraso ms: p50=%d p90=%d p99=%d max=%d\n",
		*peleas, len(todos), enviados, recib, 100*float64(recib)/float64(max(1, enviados)), q(.5), q(.9), q(.99), q(1))
}
