#!/usr/bin/env python3
"""Comprueba desde TU PC (o cualquier lugar de internet) que el servidor responde en los tres puertos que usa el juego.

    python comprobar_conexion.py 123.45.67.89          (puerto 8080 por defecto)
    python comprobar_conexion.py 123.45.67.89 8080

No crea cuentas ni toca nada del servidor. Solo necesita Python (sin librerias extra)."""
import os, socket, struct, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
HOST = sys.argv[1] if len(sys.argv) > 1 else None
PUERTO = int(sys.argv[2]) if len(sys.argv) > 2 else 8080
if not HOST:
    print(__doc__); sys.exit(2)


def tlv(tipo, seq, cmd, payload):
    cuerpo = struct.pack('>HI', 2, seq) + struct.pack('>HI', 6, cmd) + struct.pack('>HB', 5, 2) + struct.pack('>HI', 4, len(payload)) + payload
    return struct.pack('>HI', tipo, len(cuerpo)) + cuerpo


def prueba_tcp():
    """El canal del juego: pide la hora del servidor (no hace falta cuenta)."""
    from cliente_prueba import Cliente
    c = Cliente('prueba', HOST, PUERTO)
    r = c.pedir('QueryServerTimeReq', {}, ver=False); c.s.close()
    return any(t == 'QueryServerTimeRsp' for _, t, _ in r)


def prueba_udp(puerto, datos, espera):
    """Devuelve el tiempo de ida y vuelta en ms, o None si no contesta."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.settimeout(1.0)
    try:
        for _ in range(3):
            t0 = time.time(); s.sendto(datos, (HOST, puerto))
            try:
                r, _ = s.recvfrom(4096)
                if espera(r): return (time.time() - t0) * 1000
            except socket.timeout:
                pass
            except OSError:
                return None
        return None
    finally:
        s.close()


def main():
    print('Comprobando %s ...\n' % HOST)
    try:
        ok = prueba_tcp()
    except Exception as e:
        ok = False; print('   (TCP: %s)' % e)
    print(('  OK   ' if ok else '  FALLA') + '  TCP %d  (juego: login, salas, chat)' % PUERTO)
    ping = tlv(1, 7, 1, struct.pack('<q', int(time.time() * 1000)))
    rtt = [prueba_udp(PUERTO - 1, ping, lambda r: r == b'\x00\x02' + ping[2:]) for _ in range(5)]
    ok2 = any(x is not None for x in rtt); validos = [x for x in rtt if x is not None]
    print(('  OK   ' if ok2 else '  FALLA') + '  UDP %d  (ping antes de la pelea)%s' % (PUERTO - 1, '  ping %.0f ms' % min(validos) if ok2 else ''))
    wask = struct.pack('<IBBHIIII', 6666, 83, 0, 128, 0, 0, 0, 0)          # KCP "dime tu ventana": el relay contesta
    ok3 = prueba_udp(PUERTO, wask, lambda r: len(r) >= 24 and r[4] in (82, 84)) is not None
    print(('  OK   ' if ok3 else '  FALLA') + '  UDP %d  (la pelea en tiempo real)' % PUERTO)
    print()
    if ok and ok2 and ok3:
        print('Todo bien: los telefonos deberian poder conectarse y pelear.')
        print('El ping de arriba es desde este equipo; por debajo de ~80 ms la pelea deberia ir fluida.')
    else:
        print('Algo no llega. Revisa:')
        if not ok: print('  - TCP %d: que el servidor este corriendo, la regla TCP en la Security List de Oracle y la IP.' % PUERTO)
        if not (ok2 and ok3): print('  - UDP: la regla UDP %d-%d en la Security List de Oracle (o en el firewall de Windows si es tu PC).' % (PUERTO - 1, PUERTO))
        print('  - Que el servidor sea la version nueva (la que escucha tambien en el puerto %d).' % (PUERTO - 1))
    return 0 if ok and ok2 and ok3 else 1


if __name__ == '__main__':
    sys.exit(main())
