import { BoardFigure } from "@/components/BoardFigure";
import { WiringDiagram } from "@/components/WiringDiagram";
import { photo } from "@/lib/data";

export const metadata = { title: "Hardware · Rootline" };

const FAULTS = [
  ["hwWeakSignal", "Board A", "Transmit power to 1 dBm (from about 20 dBm). Reverts by itself after 8 minutes at the latest.", "netemLoss"],
  ["hwContention", "Board B", "30 Mbit/s of UDP to the laptop for 5 minutes on the same 2.4 GHz channel.", "toxiLatency"],
  ["hwWifiOutage", "Board A", "Radio off for 30 seconds, then back on. Replaces unplugging the board by hand.", "toxiReset"],
];

export default function Hardware() {
  return (
    <div className="wrap page">
      <p className="eyebrow">
        <b>●</b> Hardware arm · exploratory
      </p>
      <h1 className="page-title">
        Real Wi-Fi faults on <em>two Arduino UNO Q</em> boards.
      </h1>
      <p className="lede">
        Emulated network faults are clean: a proxy adds exactly 300 ms, or drops exactly 5% of
        packets. A real radio link fails messily. The hardware arm routes one link of the shop over
        real Wi-Fi, degrades it, and asks whether models read it the way they read the emulated
        version (&quot;emulation validity&quot;). It is reported next to the main results, outside the
        hypothesis tests.
      </p>

      <div className="boards" style={{ marginTop: 56 }}>
        <div className="board">
          <BoardFigure board="A" photo={photo("board-a")} />
          <h3>Board A, the relay</h3>
          <p>
            A small Go program, <code>edge-relay</code>, runs as a systemd service on the board&apos;s
            Linux side. In the hardware wiring, checkout sends its payment requests to the board, which
            forwards them over Wi-Fi to payment on the laptop.
          </p>
        </div>
        <div className="board">
          <BoardFigure board="B" photo={photo("board-b")} />
          <h3>Board B, the crowd</h3>
          <p>
            Runs iperf3 to fill the 2.4 GHz channel with traffic to a server on the laptop, and can log
            signal strength and throughput. The optional demo panel (buttons, LEDs and a small display on
            the microcontroller) lives here too, for the launch video only.
          </p>
        </div>
      </div>

      <h2>Wiring</h2>
      <WiringDiagram />

      <h2>The three faults</h2>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Fault</th>
              <th>Board</th>
              <th>What happens</th>
              <th>Compared with</th>
            </tr>
          </thead>
          <tbody>
            {FAULTS.map(([n, b, d, e]) => (
              <tr key={n}>
                <td className="mono">{n}</td>
                <td>{b}</td>
                <td>{d}</td>
                <td className="mono">{e}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2>Safety and limits</h2>
      <ul className="limits">
        <li>
          <div>
            <strong>Own network only</strong>
            <p>The contention script refuses any server outside private address ranges and points at the laptop.</p>
          </div>
        </li>
        <li>
          <div>
            <strong>Undo is built in</strong>
            <p>Each fault schedules its own revert on the board before it starts, so a lost SSH session never leaves it in place.</p>
          </div>
        </li>
        <li>
          <div>
            <strong>Not the same as distance</strong>
            <p>Lower transmit power degrades Board A&apos;s uplink only. With the board near the router it left no visible trace in the shop&apos;s calls.</p>
          </div>
        </li>
        <li>
          <div>
            <strong>Same services as emulated</strong>
            <p>The relay sent no telemetry of its own, so hardware snapshots show the same services as emulated ones.</p>
          </div>
        </li>
      </ul>
      <p className="q-deferred">
        Results for the 12 hardware snapshots appear on the home page once they are scored.
      </p>
    </div>
  );
}
