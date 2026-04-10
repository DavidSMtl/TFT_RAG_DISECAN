//Toggle del sidebar (móvil)
function toggleSidebar() {
    document.getElementById("sidebar").classList.toggle("open");
    document.getElementById("sidebar-overlay").classList.toggle("open");
}

//Limpiar filtros
function clearFilters() {
    document.getElementById("filter-legislature").value = "";
    document.getElementById("filter-speaker").value = "";
    document.getElementById("filter-session").value = "";
    document.getElementById("filter-date").value = "";
}

//Añadir un mensaje al chat
function addMessage(text, role) {
    const messagesEl = document.getElementById("messages");

    const avatar = role === "user" ? "👤" : "🤖";
    const div = document.createElement("div");
    div.className = "msg";
    div.innerHTML = `
        <div class="msg-avatar ${role}">${avatar}</div>
        <div class="msg-bubble ${role}">${text}</div>
    `;
    messagesEl.appendChild(div);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    return div;
}

//Añadir respuesta del asistente con fuentes
function addBotMessage(answer, sources) {
    const messagesEl = document.getElementById("messages");

    let sourcesHtml = "";
    if (sources && sources.length > 0) {
        const s = sources[0]; // mostramos la primera fuente
        sourcesHtml = `
            <button class="sources-btn" onclick="this.nextElementSibling.classList.toggle('open')">
                Ver Fuentes Oficiales (Diario de Sesiones)
            </button>
            <div class="sources-content">
                <div class="source-fragment">Fragmento: ${s.fragment}</div>
                <div class="source-meta">
                    Orador: ${s.speaker} · Fecha: ${s.date} · Legislatura: ${s.legislature} ·
                    <a href="${s.pdf_url}" target="_blank">Ver PDF Original</a>
                </div>
            </div>
        `;
    }

    const div = document.createElement("div");
    div.className = "msg";
    div.innerHTML = `
        <div class="msg-avatar bot"></div>
        <div class="msg-bubble bot">
            <p>${answer}</p>
            ${sourcesHtml}
        </div>
    `;
    messagesEl.appendChild(div);
    messagesEl.scrollTop = messagesEl.scrollHeight;
}

//Envío del formulario
async function sendMessage(event) {
    event.preventDefault();

    const input = document.getElementById("chat-input");
    const query = input.value.trim();
    if (!query) return;

    input.value = "";
    addMessage(query, "user");

    const loadingDiv = addMessage("...", "bot");

    try {
        const response = await fetch("/api/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                query: query,
                filters: {
                    legislatura: document.getElementById("filter-legislature").value,
                    orador: document.getElementById("filter-speaker").value,
                    sesion: document.getElementById("filter-session").value,
                    fecha: document.getElementById("filter-date").value,
                }
            }),
        });

        const data = await response.json();
        loadingDiv.remove();
        addBotMessage(data.answer, data.sources);

    } catch (error) {
        loadingDiv.querySelector(".msg-bubble").textContent = "Error al conectar con el servidor.";
    }
}
