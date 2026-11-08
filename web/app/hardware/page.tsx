export const metadata = { title: "Hardware · Rootline" };

export default function Hardware() {
  return (
    <>
      <h1>Hardware: real Wi-Fi faults</h1>
      <p className="lede">
        Two Arduino UNO Q boards test whether models diagnose a genuinely degraded Wi-Fi link the
        same way they diagnose an emulated one (&quot;emulation validity&quot;).
      </p>

      <div className="grid">
        <div className="card">
          <strong>Board A: real-network relay</strong>
          <p>
            A small Go TCP relay on the board&apos;s Linux side carries the checkout → payment
            traffic over Wi-Fi instead of through Toxiproxy, and exports OpenTelemetry data to the
            snapshotter. Faults: weak signal, a congested 2.4 GHz band, and a 30-second power cut.
          </p>
        </div>
        <div className="card">
          <strong>Board B: contention and demo panel</strong>
          <p>
            Generates controlled contention on the lab&apos;s own network with iperf3 and logs
            signal strength and throughput. Two buttons trigger a fault and a reset through the
            controller; LEDs show healthy, faulty and diagnosing, and a small display shows the
            model&apos;s top hypothesis.
          </p>
        </div>
      </div>

      <h2>Safety</h2>
      <p>
        Contention is created only on the lab&apos;s own isolated network and channel, never on
        anyone else&apos;s.
      </p>

      <div className="card empty" style={{ marginTop: 24 }}>
        Photos and hardware results are added after the hardware snapshots are collected.
      </div>
    </>
  );
}
