(function () {
    "use strict";
    const canvas = document.getElementById("progressChart");
    if (!canvas || !window.Chart || !window.progressData) return;

    new window.Chart(canvas, {
        type: "line",
        data: {
            labels: window.progressData.labels,
            datasets: [
                {
                    label: "Pain score",
                    data: window.progressData.pain,
                    borderColor: "#d99777",
                    backgroundColor: "rgba(217,151,119,.1)",
                    pointBackgroundColor: "#ffffff",
                    pointBorderColor: "#d99777",
                    pointBorderWidth: 3,
                    pointRadius: 4,
                    tension: .38,
                    yAxisID: "pain",
                    fill: true
                },
                {
                    label: "Mobility",
                    data: window.progressData.mobility,
                    borderColor: "#377b68",
                    backgroundColor: "rgba(55,123,104,.06)",
                    pointBackgroundColor: "#ffffff",
                    pointBorderColor: "#377b68",
                    pointBorderWidth: 3,
                    pointRadius: 4,
                    tension: .38,
                    yAxisID: "mobility"
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false }, tooltip: { backgroundColor: "#18332d", padding: 12, cornerRadius: 9 } },
            interaction: { intersect: false, mode: "index" },
            scales: {
                x: { grid: { display: false }, border: { display: false }, ticks: { color: "#748981", font: { size: 11 } } },
                pain: { position: "left", min: 0, max: 10, grid: { color: "#edf2ef" }, border: { display: false }, ticks: { color: "#748981", stepSize: 2 } },
                mobility: { position: "right", min: 0, max: 100, display: false, grid: { display: false } }
            }
        }
    });
})();
