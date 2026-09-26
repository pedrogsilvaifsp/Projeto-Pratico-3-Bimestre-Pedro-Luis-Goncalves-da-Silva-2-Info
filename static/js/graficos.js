document.addEventListener('DOMContentLoaded', function () {
    const canvas = document.getElementById('graficoProdutos');
    if (!canvas || typeof Chart === 'undefined') return;

    const data = window.produtosVendidos || {};
    const labels = Object.keys(data);
    const values = Object.values(data);

    new Chart(canvas, {
        type: 'bar',
        data: {
            labels,
            datasets: [{
                label: 'Unidades vendidas',
                data: values,
                borderRadius: 8,
                backgroundColor: '#10b981',
                hoverBackgroundColor: '#059669',
                maxBarThickness: 38
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
                x: { grid: { display: false }, ticks: { color: '#7b8794' } },
                y: { beginAtZero: true, grid: { color: '#edf1f5' }, ticks: { color: '#7b8794', precision: 0 } }
            }
        }
    });
});
