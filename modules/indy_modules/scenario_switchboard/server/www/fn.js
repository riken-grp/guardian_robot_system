async function fetchData() {
    const res = await fetch("/api/data");
    if (!res.ok) {
        alert("Error fetching data");
        return;
    }
    return res.json();
}

function createItemRow(doc, scenario_type) {
    const row = document.createElement("div");
    row.className = "item-row";

    const nameSpan = document.createElement("span");
    nameSpan.className = "item-name";
    nameSpan.textContent = doc.name || "(no name)";
    row.appendChild(nameSpan);

    const rightSide = document.createElement("div");
    rightSide.style.display = "flex";
    rightSide.style.alignItems = "center";

    const toggle = document.createElement("div");
    toggle.className = "toggle-switch" + (doc.status === "active" ? " on" : "");
    toggle.dataset.id = doc._id;
    toggle.dataset.type = scenario_type;

    const knob = document.createElement("div");
    knob.className = "toggle-knob";
    toggle.appendChild(knob);

    // const label = document.createElement("title");
    // label.className = "status-label";
    // label.textContent = doc.status === "active" ? "Active" : "Inactive";
    toggle.title = (doc.status === "active" ? "Active" : "Inactive");

    toggle.addEventListener("click", async () => {
        // Optimistic UI toggle
        toggle.classList.toggle("on");
        let newStatus = toggle.classList.contains("on") ? "active" : "inactive";

        try {
            const res = await fetch("/api/toggle", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ id: doc._id, scenario_type: scenario_type, status: newStatus }),
            });

            if (!res.ok) {
                throw new Error("Request failed");
            }

            const data = await res.json();
            // Ensure UI matches server result
            if (!data.modified) {
                // Reverts
                toggle.classList.toggle("on");
                newStatus = toggle.classList.contains("on") ? "active" : "inactive";
            }

            toggle.title = newStatus === "active" ? "Active" : "Inactive";
        } catch (err) {
            alert("Error updating status; reverting.");
            // revert UI
            const isActive = doc.status === "active";
            toggle.classList.toggle("on", isActive);
            toggle.title = isActive ? "Active" : "Inactive";
        }
    });

    rightSide.appendChild(toggle);
    // toggle.appendChild(label);
    row.appendChild(rightSide);

    return row;
}

async function render() {
    const data = await fetchData();
    if (!data) return;

    const scenarioList = document.getElementById("scenario-list");
    const subscenarioList = document.getElementById("subscenario-list");

    scenarioList.innerHTML = "";
    subscenarioList.innerHTML = "";

    data.scenarios.forEach((s) => {
        scenarioList.appendChild(createItemRow(s, "scenario"));
    });

    data.subscenarios.forEach((ss) => {
        subscenarioList.appendChild(createItemRow(ss, "subscenario"));
    });
}

// Initial load
window.addEventListener("load", function () {
    document.getElementById("refresh-button").addEventListener("click", render);
    render();
});
