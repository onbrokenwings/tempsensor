const state = {
  currentRange: '24h',
  charts: {},
};

const rangeButtons = () => Array.from(document.querySelectorAll('.range-button'));
const temperatureEl = () => document.getElementById('current-temperature');
const humidityEl = () => document.getElementById('current-humidity');
const batteryEl = () => document.getElementById('current-battery');
const dateEl = () => document.getElementById('current-date');
const timeEl = () => document.getElementById('current-time');
const historyBody = () => document.getElementById('history-body');

const formatNumber = (value, suffix, digits = 2) => {
  if (value === null || value === undefined) {
    return '—';
  }
  return `${Number(value).toFixed(digits)} ${suffix}`;
};

const chartBucketForRange = (range) => {
  if (range === '1M') return 'week';
  if (range === '24h') return 'hour';
  return 'day';
};

const formatChartTickLabel = (tsLocal, range, index) => {
  const date = new Date(tsLocal.replace(' ', 'T'));
  if (Number.isNaN(date.getTime())) {
    return tsLocal;
  }

  const day = String(date.getDate()).padStart(2, '0');
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const hour = String(date.getHours()).padStart(2, '0');

  if (range === '24h') {
    return [9, 17, 22].includes(date.getHours()) ? `${hour}:00` : '';
  }

  if (range === '7d') {
    return index % 2 === 0 ? `${day}/${month}` : '';
  }

  if (range === '14d') {
    return index % 3 === 0 ? `${day}/${month}` : '';
  }

  return `${day}/${month}`;
};

const createChart = (canvasId, label, color, yMin = undefined, yMax = undefined) => {
  const ctx = document.getElementById(canvasId);
  return new Chart(ctx, {
    type: 'line',
    data: {
      labels: [],
      datasets: [{
        label,
        data: [],
        fill: true,
        backgroundColor: `${color}33`,
        borderColor: color,
        borderWidth: 2,
        tension: 0.15,
        pointRadius: 0,
        pointHoverRadius: 3,
        spanGaps: true,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { mode: 'index', intersect: false },
      },
      scales: {
        x: {
          grid: { display: false },
          ticks: {
            display: true,
            maxRotation: 0,
            autoSkip: false,
          },
        },
        y: {
          beginAtZero: false,
          grid: { display: false },
          ticks: {
            precision: 0,
            maxTicksLimit: 6,
          },
          ...(yMin !== undefined ? { min: yMin } : {}),
          ...(yMax !== undefined ? { max: yMax } : {}),
        },
      },
    },
  });
};

const updateChart = (chart, labels, values, range) => {
  chart.data.labels = labels;
  chart.data.datasets[0].data = values;
  chart.options.scales.x.ticks.callback = (value, index) => formatChartTickLabel(labels[index] ?? value, range, index);
  chart.update();
};

const updateLatest = (data) => {
  temperatureEl().textContent = formatNumber(data?.temperature_c, '°C');
  humidityEl().textContent = formatNumber(data?.humidity_pct, '%');
  batteryEl().textContent = formatNumber(data?.battery_pct, '%', 0);
  dateEl().textContent = data?.date || '—';
  timeEl().textContent = data?.time || '—';
};

const renderHistoryTable = (rows) => {
  const body = historyBody();
  if (!body) return;
  body.innerHTML = rows
    .map((row) => {
      const temperature = row.temperature_c === null ? '—' : row.temperature_c.toFixed(2);
      const humidity = row.humidity_pct === null ? '—' : row.humidity_pct.toFixed(2);
      return `
        <tr>
          <td>${row.ts_local}</td>
          <td>${temperature}</td>
          <td>${humidity}</td>
          <td>${row.count ?? 1}</td>
        </tr>`;
    })
    .join('');
};

const loadLatest = async () => {
  try {
    const response = await fetch('/api/latest', { cache: 'no-store' });
    if (!response.ok) return;
    const data = await response.json();
    if (data) updateLatest(data);
  } catch (err) {
    console.error('Error fetching latest:', err);
  }
};

const loadHistory = async (range) => {
  try {
    const response = await fetch(`/api/history?range=${range}&bucket=${chartBucketForRange(range)}`, { cache: 'no-store' });
    if (!response.ok) return;
    const rows = await response.json();
    const labels = rows.map((row) => row.ts_local);
    const temperatureValues = rows.map((row) => (row.temperature_c === null ? null : Number(row.temperature_c)));
    const humidityValues = rows.map((row) => (row.humidity_pct === null ? null : Number(row.humidity_pct)));
    const batteryValues = rows.map((row) => (row.battery_pct === null ? null : Number(row.battery_pct)));

    updateChart(state.charts.temperature, labels, temperatureValues, range);
    updateChart(state.charts.humidity, labels, humidityValues, range);
    updateChart(state.charts.battery, labels, batteryValues, range);
  } catch (err) {
    console.error('Error fetching history:', err);
  }
};

const loadHistoryTable = async (range) => {
  try {
    const response = await fetch(`/api/history?range=${range}`, { cache: 'no-store' });
    if (!response.ok) return;
    const rows = await response.json();
    renderHistoryTable(rows);
  } catch (err) {
    console.error('Error fetching history table:', err);
  }
};

const setActiveRangeButton = (range) => {
  rangeButtons().forEach((button) => {
    button.classList.toggle('active', button.dataset.range === range);
  });
};

const init = () => {
  state.charts.temperature = createChart('temperature-chart', 'Temperatura (°C)', '#ef4444');
  state.charts.humidity = createChart('humidity-chart', 'Humedad (%)', '#22c55e');
  state.charts.battery = createChart('battery-chart', 'Batería (%)', '#3b82f6', 0, 100);

  rangeButtons().forEach((button) => {
    button.addEventListener('click', () => {
      const selected = button.dataset.range;
      state.currentRange = selected;
      setActiveRangeButton(selected);
      loadHistory(selected);
      loadHistoryTable(selected);
    });
  });

  setActiveRangeButton(state.currentRange);
  loadLatest();
  loadHistory(state.currentRange);
  loadHistoryTable(state.currentRange);
  setInterval(loadLatest, 5000);
};

window.addEventListener('DOMContentLoaded', init);
