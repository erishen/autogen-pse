import { Chart, LineController, LineElement, PointElement, LinearScale, CategoryScale, Tooltip } from "chart.js";
import { Line } from "react-chartjs-2";

Chart.register(LineController, LineElement, PointElement, LinearScale, CategoryScale, Tooltip);

export default function TrendChart({ data }) {
  if (!data || !data.length) {
    return <p style={{ color: "#999", textAlign: "center", padding: 40 }}>暂无数据</p>;
  }
  const reversed = [...data].reverse();
  const chartData = {
    labels: reversed.map((a) => a.date.slice(4, 6) + "/" + a.date.slice(6)),
    datasets: [
      {
        label: "总资产(万元)",
        data: reversed.map((a) => parseFloat(a.total_assets || 0)),
        borderColor: "#1a1a2e",
        backgroundColor: "rgba(26,26,46,0.1)",
        tension: 0.3,
        fill: true,
      },
    ],
  };
  return (
    <Line
      data={chartData}
      options={{
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: { y: { beginAtZero: false } },
      }}
    />
  );
}
