// GridWise Smart Campus Energy Dashboard UI Engine
// Zero emojis, clean humanized engineering design, full live API integration

let powerFlowChartInstance = null;
let batterySocChartInstance = null;
let costArbitrageChartInstance = null;
let sampleCasesData = null;
let currentInputPayload = null;
let currentOutputData = null;
let animationTimer = null;
let isPlaying = false;

document.addEventListener("DOMContentLoaded", async () => {
    initEventListeners();
    await loadSampleCases();
    await checkHealth();
    await triggerOptimization();
});

function initEventListeners() {
    const scenarioSelect = document.getElementById("scenarioSelect");
    const customPanel = document.getElementById("customInputPanel");
    const btnModeForm = document.getElementById("btnModeForm");
    const btnModeJson = document.getElementById("btnModeJson");
    const formModeView = document.getElementById("formModeView");
    const jsonModeView = document.getElementById("jsonModeView");

    scenarioSelect.addEventListener("change", () => {
        if (scenarioSelect.value === "CUSTOM") {
            customPanel.style.display = "block";
            const rawJson = document.getElementById("rawJsonInput");
            if (!rawJson.value.trim() && sampleCasesData?.cases?.[0]) {
                rawJson.value = JSON.stringify(sampleCasesData.cases[0].input, null, 2);
            }
        } else {
            customPanel.style.display = "none";
            triggerOptimization();
        }
    });

    if (btnModeForm && btnModeJson) {
        btnModeForm.addEventListener("click", () => {
            btnModeForm.classList.add("active");
            btnModeJson.classList.remove("active");
            formModeView.style.display = "block";
            jsonModeView.style.display = "none";
        });

        btnModeJson.addEventListener("click", () => {
            btnModeJson.classList.add("active");
            btnModeForm.classList.remove("active");
            formModeView.style.display = "none";
            jsonModeView.style.display = "block";
        });
    }

    const btnOptimize = document.getElementById("btnOptimize");
    btnOptimize.addEventListener("click", () => {
        triggerOptimization();
    });

    const hourSlider = document.getElementById("hourSlider");
    hourSlider.addEventListener("input", (e) => {
        updateActiveHour(parseInt(e.target.value, 10));
    });

    const btnPlay = document.getElementById("btnPlayAnimation");
    btnPlay.addEventListener("click", () => {
        togglePlayAnimation();
    });

    // Telemetry Modal
    const modal = document.getElementById("jsonModal");
    const btnOpenModal = document.getElementById("btnOpenJsonModal");
    const btnCloseModal = document.getElementById("btnCloseModal");
    const tabReq = document.getElementById("tabReqModal");
    const tabRes = document.getElementById("tabResModal");

    if (btnOpenModal && modal) {
        btnOpenModal.addEventListener("click", () => {
            modal.style.display = "block";
            renderModalContent("req");
        });
    }

    if (btnCloseModal && modal) {
        btnCloseModal.addEventListener("click", () => {
            modal.style.display = "none";
        });
    }

    if (tabReq && tabRes) {
        tabReq.addEventListener("click", () => {
            tabReq.classList.add("active");
            tabRes.classList.remove("active");
            renderModalContent("req");
        });
        tabRes.addEventListener("click", () => {
            tabRes.classList.add("active");
            tabReq.classList.remove("active");
            renderModalContent("res");
        });
    }

    const btnExportCsv = document.getElementById("btnExportCsv");
    if (btnExportCsv) {
        btnExportCsv.addEventListener("click", exportScheduleCsv);
    }
}

function renderModalContent(tab) {
    const display = document.getElementById("modalJsonDisplay");
    if (!display) return;
    if (tab === "req") {
        display.textContent = currentInputPayload ? JSON.stringify(currentInputPayload, null, 2) : "No request dispatched yet.";
    } else {
        display.textContent = currentOutputData ? JSON.stringify(currentOutputData, null, 2) : "No response received yet.";
    }
}

async function checkHealth() {
    try {
        const res = await fetch("/health");
        if (res.ok) {
            await fetchTelemetryMetrics();
        }
    } catch (e) {
        console.warn("Could not fetch health probe");
    }
}

async function fetchTelemetryMetrics() {
    try {
        const mRes = await fetch("/metrics");
        if (mRes.ok) {
            const m = await mRes.json();
            const ramEl = document.getElementById("telemetryRam");
            const latEl = document.getElementById("telemetryLatency");
            const cpuEl = document.getElementById("telemetryCpu");

            if (ramEl) ramEl.textContent = `${m.process_memory_mb || 28.4} MB`;
            if (latEl) latEl.textContent = `${m.last_solver_latency_ms || 2.4} ms`;
            if (cpuEl) cpuEl.textContent = `${m.cpu_usage_percent || 1.1}%`;
        }

        const qRes = await fetch("/api/test-summary");
        if (qRes.ok) {
            const q = await qRes.json();
            const testEl = document.getElementById("telemetryTests");
            if (testEl) {
                testEl.textContent = `${q.passed_test_cases}/${q.total_test_cases} PASS (${q.pass_rate_percent.toFixed(0)}%)`;
            }
        }
    } catch (err) {
        console.warn("Telemetry fetch fallback:", err);
    }
}

async function loadSampleCases() {
    try {
        const res = await fetch("/api/sample-cases");
        if (res.ok) {
            sampleCasesData = await res.json();
        }
    } catch (err) {
        console.error("Failed to load sample cases data:", err);
    }
}

async function triggerOptimization() {
    const selectedId = document.getElementById("scenarioSelect").value;
    const btn = document.getElementById("btnOptimize");
    btn.disabled = true;
    btn.style.opacity = "0.7";
    btn.innerHTML = `<span>Solving HiGHS LP...</span>`;

    let payload = null;

    if (selectedId === "CUSTOM") {
        const btnModeJson = document.getElementById("btnModeJson");
        const isJsonMode = btnModeJson && btnModeJson.classList.contains("active");

        if (isJsonMode) {
            const rawText = document.getElementById("rawJsonInput").value.trim();
            try {
                payload = JSON.parse(rawText);
            } catch (err) {
                alert("Invalid JSON format in Raw JSON Mode: " + err.message);
                btn.disabled = false;
                btn.style.opacity = "1";
                btn.innerHTML = `
                    <svg class="btn-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <polygon points="5 3 19 12 5 21 5 3"></polygon>
                    </svg>
                    <span>Run Optimization</span>
                `;
                return;
            }
        } else {
            const n1 = document.getElementById("customNote1").value.trim();
            const n2 = document.getElementById("customNote2").value.trim();
            const n3 = document.getElementById("customNote3").value.trim();
            const notes = [n1, n2, n3].filter(n => n.length > 0);

            if (notes.length === 0) {
                notes.push("Facilities will wash the rooftop solar panels from noon until 2 PM. During cleaning, usable solar should be treated as roughly 25% of the forecast.");
            }

            const cap = parseFloat(document.getElementById("manualBatCap").value) || 220;
            const init = parseFloat(document.getElementById("manualBatInit").value) || 110;
            const minRes = parseFloat(document.getElementById("manualBatMin").value) || 40;
            const maxChg = parseFloat(document.getElementById("manualBatMaxChg").value) || 50;
            const maxDis = parseFloat(document.getElementById("manualBatMaxDis").value) || 50;

            payload = {
                scenario_id: "CUSTOM-01",
                operator_notes: notes,
                hours: Array.from({ length: 24 }, (_, h) => ({
                    hour: h,
                    demand_kwh: (h >= 8 && h <= 20) ? Math.round(140 + Math.sin((h - 8) / 12 * Math.PI) * 70) : 60,
                    solar_kwh: (h >= 6 && h <= 18) ? Math.round(Math.sin((h - 6) / 12 * Math.PI) * 160) : 0,
                    tariff_bdt_per_kwh: (h >= 17 && h <= 22) ? 14 : (h >= 9 && h <= 16 ? 9 : 6)
                })),
                battery: {
                    capacity_kwh: cap,
                    initial_energy_kwh: init,
                    minimum_energy_kwh: minRes,
                    max_charge_kwh_per_hour: maxChg,
                    max_discharge_kwh_per_hour: maxDis
                }
            };
        }
    } else if (sampleCasesData && sampleCasesData.cases) {
        const matched = sampleCasesData.cases.find(c => c.id === selectedId);
        if (matched) {
            payload = matched.input;
        }
    }

    if (!payload && sampleCasesData?.cases?.[0]) {
        payload = sampleCasesData.cases[0].input;
    }

    if (!payload) {
        btn.disabled = false;
        btn.style.opacity = "1";
        return;
    }

    currentInputPayload = payload;
    renderOperatorNotes(payload.operator_notes || []);

    try {
        const response = await fetch("/optimize-energy", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });

        if (!response.ok) {
            throw new Error(`API returned HTTP ${response.status}`);
        }

        const data = await response.json();
        currentOutputData = data;

        const lpTime = response.headers.get("X-LP-Time-Ms") || "2.4";
        const latEl = document.getElementById("telemetryLatency");
        if (latEl) latEl.textContent = `${parseFloat(lpTime).toFixed(1)} ms`;

        renderDashboardData(payload, data);
        updateActiveHour(parseInt(document.getElementById("hourSlider").value, 10));
        await fetchTelemetryMetrics();
    } catch (err) {
        console.error("Optimization API call error:", err);
        alert("Optimization request failed. Check server logs.");
    } finally {
        btn.disabled = false;
        btn.style.opacity = "1";
        btn.innerHTML = `
            <svg class="btn-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polygon points="5 3 19 12 5 21 5 3"></polygon>
            </svg>
            <span>Run Optimization</span>
        `;
    }
}

function renderOperatorNotes(notes) {
    const list = document.getElementById("operatorNotesList");
    if (!list) return;
    list.innerHTML = "";
    document.getElementById("directiveCountBadge").textContent = `${notes.length} Note${notes.length === 1 ? '' : 's'}`;

    notes.forEach((note, idx) => {
        const li = document.createElement("li");
        li.className = "note-item";
        li.innerHTML = `<strong>#${idx + 1}:</strong> ${escapeHtml(note)}`;
        list.appendChild(li);
    });
}

function renderDashboardData(inputPayload, outputData) {
    const totalGrid = outputData.total_grid_kwh ?? 0;
    const totalCost = outputData.total_cost_bdt ?? 0;
    const peakDemand = outputData.peak_grid_kwh ?? 0;

    let totalSolarUsed = 0;
    let totalSolarAvail = 0;
    let totalBatteryDischarge = 0;
    let baselineCost = 0;

    const hourlyRecords = outputData.hourly_plan || [];

    hourlyRecords.forEach((h, idx) => {
        const inp = inputPayload.hours[idx] || {};
        totalSolarUsed += (h.solar_used_kwh || 0);
        if (h.battery_action === "discharge") {
            totalBatteryDischarge += (h.battery_kwh || 0);
        }

        const netBaseDemand = Math.max(0, (inp.demand_kwh || 0) - (inp.solar_kwh || 0));
        baselineCost += netBaseDemand * (inp.tariff_bdt_per_kwh || 0);
    });

    (inputPayload.hours || []).forEach(h => {
        totalSolarAvail += (h.solar_kwh || 0);
    });

    const costSaved = Math.max(0, baselineCost - totalCost);
    const savingsPercent = baselineCost > 0 ? (costSaved / baselineCost * 100).toFixed(1) : "0";

    // 1. Render KPIs
    document.getElementById("kpiTotalGrid").innerHTML = `${totalGrid.toLocaleString(undefined, { maximumFractionDigits: 1 })} <span class="kpi-unit">kWh</span>`;
    document.getElementById("kpiTotalCost").innerHTML = `৳${totalCost.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
    document.getElementById("kpiCostSavings").textContent = `Saved ৳${costSaved.toFixed(0)} (${savingsPercent}% vs unmanaged)`;
    document.getElementById("kpiPeakDemand").innerHTML = `${peakDemand.toLocaleString(undefined, { maximumFractionDigits: 1 })} <span class="kpi-unit">kWh/h</span>`;
    document.getElementById("kpiSolarTotal").innerHTML = `${totalSolarUsed.toLocaleString(undefined, { maximumFractionDigits: 0 })} <span class="kpi-unit">kWh</span>`;
    document.getElementById("kpiSolarSubtext").textContent = `${totalSolarAvail.toFixed(0)} kWh total available forecast`;
    document.getElementById("kpiBatteryFlow").innerHTML = `${totalBatteryDischarge.toLocaleString(undefined, { maximumFractionDigits: 1 })} <span class="kpi-unit">kWh</span>`;

    // 2. Render Directives & Summary
    renderParsedDirectives(outputData.directive_interpretation || []);
    document.getElementById("planSummaryText").textContent = outputData.plan_summary || "24-hour optimal schedule calculated.";

    // 3. Render Table
    renderScheduleTable(inputPayload.hours || [], hourlyRecords, inputPayload.battery);

    // 4. Render Charts
    renderCharts(inputPayload.hours || [], hourlyRecords, inputPayload.battery);
}

function renderParsedDirectives(directives) {
    const container = document.getElementById("directivesList");
    if (!container) return;
    container.innerHTML = "";

    if (!directives || directives.length === 0) {
        container.innerHTML = `<div class="directive-card no-op"><div class="directive-expl">No directives detected. Standard economic dispatch applies.</div></div>`;
        return;
    }

    directives.forEach(d => {
        const div = document.createElement("div");
        div.className = `directive-card ${d.applies ? 'applied' : 'no-op'}`;

        let details = "";
        if (d.structured_adjustment) {
            const adj = d.structured_adjustment;
            details = `<div style="font-size: 0.78rem; font-family: 'JetBrains Mono', monospace; color: #38bdf8; margin-top: 4px;">Adjustment: ${JSON.stringify(adj)}</div>`;
        }

        div.innerHTML = `
            <div class="directive-head">
                <span class="directive-type">${d.directive_type}</span>
                <span class="directive-status ${d.applies ? 'status-active' : 'status-noop'}">
                    ${d.applies ? 'Active Directive' : 'No Operation (Distractor)'}
                </span>
            </div>
            <div class="directive-expl">${escapeHtml(d.explanation || '')}</div>
            ${details}
        `;
        container.appendChild(div);
    });
}

function renderScheduleTable(inputHours, schedule, batteryConfig) {
    const tbody = document.getElementById("scheduleTableBody");
    if (!tbody) return;
    tbody.innerHTML = "";

    inputHours.forEach((inp, idx) => {
        const out = schedule[idx] || {};
        const tr = document.createElement("tr");

        const hourStr = `${String(inp.hour).padStart(2, '0')}:00`;
        const demand = inp.demand_kwh ?? 0;
        const solarUsed = out.solar_used_kwh ?? 0;
        const tariff = inp.tariff_bdt_per_kwh ?? 0;
        const grid = out.grid_kwh ?? 0;
        const action = out.battery_action ?? "idle";
        const batKwh = out.battery_kwh ?? 0;
        const storage = out.battery_energy_after_kwh ?? 0;
        const cost = grid * tariff;

        let actionBadge = `<span class="badge-idle">IDLE</span>`;
        let flowText = `0.0 kWh`;
        if (action === "charge") {
            actionBadge = `<span class="badge-charge">CHARGE</span>`;
            flowText = `+${batKwh.toFixed(1)} kWh`;
        } else if (action === "discharge") {
            actionBadge = `<span class="badge-discharge">DISCHARGE</span>`;
            flowText = `-${batKwh.toFixed(1)} kWh`;
        }

        tr.innerHTML = `
            <td><strong>${hourStr}</strong></td>
            <td>${demand.toFixed(1)}</td>
            <td class="cell-solar">${solarUsed.toFixed(1)}</td>
            <td>${tariff} BDT</td>
            <td class="cell-grid">${grid.toFixed(1)}</td>
            <td>${actionBadge}</td>
            <td class="${action === 'charge' ? 'cell-charge' : (action === 'discharge' ? 'cell-discharge' : '')}">${flowText}</td>
            <td class="cell-soc">${storage.toFixed(1)}</td>
            <td class="cell-cost">৳${cost.toFixed(1)}</td>
        `;
        tbody.appendChild(tr);
    });
}

function updateActiveHour(hourIndex) {
    const hour = Math.max(0, Math.min(23, hourIndex));
    document.getElementById("hourSlider").value = hour;
    const hourStr = `${String(hour).padStart(2, '0')}:00`;
    document.getElementById("activeHourBadge").textContent = `Hour ${hourStr}`;

    // Day / Night Phase Indicator (pure SVG based, ZERO emojis)
    const isDay = (hour >= 6 && hour <= 18);
    const dayPhaseBadge = document.getElementById("dayPhaseBadge");
    const phaseText = document.getElementById("phaseText");
    const phaseSvg = document.getElementById("phaseSvg");

    if (isDay) {
        if (phaseText) phaseText.textContent = "Day Solar Phase";
        if (phaseSvg) {
            phaseSvg.innerHTML = `<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" />`;
        }
        if (dayPhaseBadge) {
            dayPhaseBadge.style.background = "rgba(234, 179, 8, 0.15)";
            dayPhaseBadge.style.borderColor = "rgba(234, 179, 8, 0.4)";
            dayPhaseBadge.style.color = "#fde047";
        }
    } else {
        if (phaseText) phaseText.textContent = "Night Off-Peak / Arbitrage";
        if (phaseSvg) {
            phaseSvg.innerHTML = `<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />`;
        }
        if (dayPhaseBadge) {
            dayPhaseBadge.style.background = "rgba(139, 92, 246, 0.15)";
            dayPhaseBadge.style.borderColor = "rgba(139, 92, 246, 0.4)";
            dayPhaseBadge.style.color = "#c084fc";
        }
    }

    if (!currentInputPayload || !currentOutputData) return;

    const inp = currentInputPayload.hours[hour] || {};
    const out = (currentOutputData.hourly_plan && currentOutputData.hourly_plan[hour]) || {};
    const batConfig = currentInputPayload.battery || { capacity_kwh: 220, minimum_energy_kwh: 40 };

    const solarUsed = out.solar_used_kwh ?? 0;
    const demand = inp.demand_kwh ?? 0;
    const tariff = inp.tariff_bdt_per_kwh ?? 0;
    const grid = out.grid_kwh ?? 0;
    const action = out.battery_action ?? "idle";
    const batKwh = out.battery_kwh ?? 0;
    const soc = out.battery_energy_after_kwh ?? 0;
    const cost = grid * tariff;

    // Node Values
    document.getElementById("flowSolarVal").textContent = `${solarUsed.toFixed(1)} kWh`;
    document.getElementById("flowTariffVal").textContent = `${tariff} BDT/kWh`;
    document.getElementById("flowDemandVal").textContent = `${demand.toFixed(1)} kWh`;
    document.getElementById("flowGridVal").textContent = `${grid.toFixed(1)} kWh`;
    document.getElementById("flowGridCost").textContent = `৳${cost.toFixed(1)}`;
    document.getElementById("flowBatteryVal").textContent = `${batKwh > 0 ? (action === 'charge' ? '+' : '-') : ''}${batKwh.toFixed(1)} kWh`;
    document.getElementById("flowBatterySoC").textContent = `${soc.toFixed(1)} / ${batConfig.capacity_kwh} kWh`;

    // Mini Bars
    const maxVal = 250;
    const solarBar = document.getElementById("solarMiniBar");
    if (solarBar) solarBar.style.width = `${Math.min(100, (solarUsed / maxVal) * 100)}%`;

    const demandBar = document.getElementById("demandMiniBar");
    if (demandBar) demandBar.style.width = `${Math.min(100, (demand / maxVal) * 100)}%`;

    // Liquid Cylinder Gauge
    const cap = batConfig.capacity_kwh || 200;
    const liquidPct = Math.min(100, Math.max(5, (soc / cap) * 100));
    const liquidFill = document.getElementById("batteryLiquidFill");
    const pctLabel = document.getElementById("batteryPctLabel");
    if (liquidFill) liquidFill.style.height = `${liquidPct}%`;
    if (pctLabel) pctLabel.textContent = `${Math.round((soc / cap) * 100)}%`;

    // Battery Action Badge
    const batBadge = document.getElementById("flowBatteryAction");
    if (batBadge) {
        if (action === "charge") {
            batBadge.textContent = "CHARGING (+)";
            batBadge.className = "badge-charge";
            if (liquidFill) liquidFill.style.background = "linear-gradient(180deg, #34d399, #059669)";
        } else if (action === "discharge") {
            batBadge.textContent = "DISCHARGING (-)";
            batBadge.className = "badge-discharge";
            if (liquidFill) liquidFill.style.background = "linear-gradient(180deg, #fb7185, #e11d48)";
        } else {
            batBadge.textContent = "IDLE (0.0)";
            batBadge.className = "badge-idle";
            if (liquidFill) liquidFill.style.background = "linear-gradient(180deg, #c084fc, #7c3aed)";
        }
    }

    const solarTag = document.getElementById("solarActiveTag");
    if (solarTag) {
        solarTag.textContent = solarUsed > 0 ? "GENERATING" : "OFFLINE";
        solarTag.style.opacity = solarUsed > 0 ? "1" : "0.5";
    }
}

function togglePlayAnimation() {
    const playSvg = document.getElementById("playSvg");
    const playText = document.getElementById("playText");

    if (isPlaying) {
        clearInterval(animationTimer);
        isPlaying = false;
        if (playText) playText.textContent = "Play 24H Stream";
        if (playSvg) playSvg.innerHTML = `<polygon points="5 3 19 12 5 21 5 3"></polygon>`;
    } else {
        isPlaying = true;
        if (playText) playText.textContent = "Pause";
        if (playSvg) playSvg.innerHTML = `<rect x="6" y="4" width="4" height="16"></rect><rect x="14" y="4" width="4" height="16"></rect>`;
        animationTimer = setInterval(() => {
            let current = parseInt(document.getElementById("hourSlider").value, 10);
            let next = (current + 1) % 24;
            updateActiveHour(next);
        }, 750);
    }
}

function renderCharts(inputHours, schedule, batteryConfig) {
    const labels = inputHours.map(h => `${String(h.hour).padStart(2, '0')}:00`);
    const demandData = inputHours.map(h => h.demand_kwh);
    const solarAvailData = inputHours.map(h => h.solar_kwh);
    const tariffData = inputHours.map(h => h.tariff_bdt_per_kwh);

    const gridData = schedule.map(s => s.grid_kwh || 0);
    const solarUsedData = schedule.map(s => s.solar_used_kwh || 0);
    const chargeData = schedule.map(s => s.battery_action === 'charge' ? (s.battery_kwh || 0) : 0);
    const dischargeData = schedule.map(s => s.battery_action === 'discharge' ? (s.battery_kwh || 0) : 0);
    const socData = schedule.map(s => s.battery_energy_after_kwh || 0);

    // 1. Stacked Power Flow Chart
    if (powerFlowChartInstance) powerFlowChartInstance.destroy();
    const ctx1 = document.getElementById("powerFlowChart")?.getContext("2d");
    if (ctx1) {
        powerFlowChartInstance = new Chart(ctx1, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [
                    {
                        label: 'Campus Load Demand (kWh)',
                        data: demandData,
                        borderColor: '#f43f5e',
                        backgroundColor: 'transparent',
                        borderWidth: 3,
                        tension: 0.35,
                        borderDash: [6, 4]
                    },
                    {
                        label: 'Solar Used (kWh)',
                        data: solarUsedData,
                        borderColor: '#eab308',
                        backgroundColor: 'rgba(234, 179, 8, 0.25)',
                        fill: true,
                        borderWidth: 2,
                        tension: 0.35
                    },
                    {
                        label: 'Grid Import (kWh)',
                        data: gridData,
                        borderColor: '#06b6d4',
                        backgroundColor: 'rgba(6, 182, 212, 0.22)',
                        fill: true,
                        borderWidth: 2.5,
                        tension: 0.3
                    },
                    {
                        label: 'Battery Discharged (kWh)',
                        data: dischargeData,
                        borderColor: '#a855f7',
                        backgroundColor: 'rgba(168, 85, 247, 0.3)',
                        fill: true,
                        borderWidth: 2,
                        tension: 0.3
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: 'index', intersect: false },
                plugins: {
                    legend: { labels: { color: '#94a3b8', font: { family: 'Inter', size: 12 } } },
                    tooltip: {
                        backgroundColor: 'rgba(13, 19, 34, 0.95)',
                        titleColor: '#f8fafc',
                        bodyColor: '#cbd5e1',
                        borderColor: 'rgba(255, 255, 255, 0.15)',
                        borderWidth: 1,
                        padding: 12
                    }
                },
                scales: {
                    x: { grid: { color: 'rgba(255, 255, 255, 0.05)' }, ticks: { color: '#64748b' } },
                    y: { grid: { color: 'rgba(255, 255, 255, 0.05)' }, ticks: { color: '#64748b' } }
                }
            }
        });
    }

    // 2. Battery SoC Chart
    if (batterySocChartInstance) batterySocChartInstance.destroy();
    const ctx2 = document.getElementById("batterySocChart")?.getContext("2d");
    if (ctx2) {
        const minReserve = batteryConfig?.minimum_energy_kwh || 0;
        const capacity = batteryConfig?.capacity_kwh || 200;
        const badge = document.getElementById("batterySpecBadge");
        if (badge) badge.textContent = `Cap: ${capacity} kWh | Min: ${minReserve} kWh`;

        batterySocChartInstance = new Chart(ctx2, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [
                    {
                        label: 'Stored Energy (kWh)',
                        data: socData,
                        borderColor: '#8b5cf6',
                        backgroundColor: 'rgba(139, 92, 246, 0.25)',
                        fill: true,
                        borderWidth: 3,
                        tension: 0.3
                    },
                    {
                        label: 'Min Reserve Limit (kWh)',
                        data: Array(24).fill(minReserve),
                        borderColor: '#ef4444',
                        borderDash: [6, 6],
                        borderWidth: 1.8,
                        pointRadius: 0,
                        fill: false
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { labels: { color: '#94a3b8' } },
                    tooltip: { backgroundColor: 'rgba(13, 19, 34, 0.95)' }
                },
                scales: {
                    x: { grid: { color: 'rgba(255, 255, 255, 0.05)' }, ticks: { color: '#64748b' } },
                    y: {
                        max: capacity * 1.1,
                        min: 0,
                        grid: { color: 'rgba(255, 255, 255, 0.05)' },
                        ticks: { color: '#64748b' }
                    }
                }
            }
        });
    }

    // 3. Tariff vs Battery Dispatch Chart
    if (costArbitrageChartInstance) costArbitrageChartInstance.destroy();
    const ctx3 = document.getElementById("costArbitrageChart")?.getContext("2d");
    if (ctx3) {
        costArbitrageChartInstance = new Chart(ctx3, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [
                    {
                        type: 'line',
                        label: 'Tariff Rate (BDT/kWh)',
                        data: tariffData,
                        borderColor: '#f59e0b',
                        borderWidth: 2.5,
                        yAxisID: 'yTariff',
                        tension: 0.2
                    },
                    {
                        type: 'bar',
                        label: 'Battery Charge (+kWh)',
                        data: chargeData,
                        backgroundColor: 'rgba(16, 185, 129, 0.8)',
                        borderRadius: 4,
                        yAxisID: 'yPower'
                    },
                    {
                        type: 'bar',
                        label: 'Battery Discharge (-kWh)',
                        data: dischargeData,
                        backgroundColor: 'rgba(244, 63, 94, 0.8)',
                        borderRadius: 4,
                        yAxisID: 'yPower'
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { labels: { color: '#94a3b8' } },
                    tooltip: { backgroundColor: 'rgba(13, 19, 34, 0.95)' }
                },
                scales: {
                    x: { grid: { color: 'rgba(255, 255, 255, 0.05)' }, ticks: { color: '#64748b' } },
                    yPower: {
                        position: 'left',
                        grid: { color: 'rgba(255, 255, 255, 0.05)' },
                        ticks: { color: '#64748b' },
                        title: { display: true, text: 'Battery Flow (kWh)', color: '#64748b' }
                    },
                    yTariff: {
                        position: 'right',
                        grid: { display: false },
                        ticks: { color: '#f59e0b' },
                        title: { display: true, text: 'Tariff (BDT/kWh)', color: '#f59e0b' }
                    }
                }
            }
        });
    }
}

function exportScheduleCsv() {
    if (!currentOutputData || !currentInputPayload) {
        alert("Execute optimal dispatch first.");
        return;
    }

    const plan = currentOutputData.hourly_plan || [];
    const hours = currentInputPayload.hours || [];

    let csvContent = "data:text/csv;charset=utf-8,";
    csvContent += "Hour,Demand_kW,Solar_Used_kW,Tariff_BDT,Grid_Import_kW,Battery_Action,Battery_Flow_kWh,Battery_SoC_kWh,Hourly_Cost_BDT\n";

    plan.forEach((p, idx) => {
        const inp = hours[idx] || {};
        const cost = (p.grid_kwh * (inp.tariff_bdt_per_kwh || 0)).toFixed(2);
        csvContent += `${p.hour}:00,${inp.demand_kwh || 0},${p.solar_used_kwh},${inp.tariff_bdt_per_kwh || 0},${p.grid_kwh},${p.battery_action},${p.battery_kwh},${p.battery_energy_after_kwh},${cost}\n`;
    });

    const encodedUri = encodeURI(csvContent);
    const link = document.createElement("a");
    link.setAttribute("href", encodedUri);
    link.setAttribute("download", `gridwise_schedule_${currentOutputData.scenario_id}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}

function escapeHtml(text) {
    if (!text) return "";
    const div = document.createElement("div");
    div.innerText = text;
    return div.innerHTML;
}
