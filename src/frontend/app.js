//Toggle del sidebar (móvil)
function toggleSidebar() {
    document.getElementById("sidebar").classList.toggle("open");
    document.getElementById("sidebar-overlay").classList.toggle("open");
}

//Limpiar filtros
function clearFilters() {
    document.getElementById("search-mode").value = "full";
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

//Aplicar resaltado de palabras clave y subrayado de frase
function applyHighlights(text, keywords, sentenceToUnderline) {
    if (!text) return "";
    let highlightedText = text;

    // 1. Subrayar la frase completa (fragmento) dentro del contexto
    if (sentenceToUnderline && sentenceToUnderline.length > 5) {
        const escapedSentence = sentenceToUnderline.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        const sentenceRegex = new RegExp(`(${escapedSentence})`, "gi");
        highlightedText = highlightedText.replace(sentenceRegex, '<span class="underlined-sentence">$1</span>');
    }

    // 2. Resaltar palabras clave individuales
    if (keywords && keywords.length > 0) {
        // Ordenamos por longitud descendente para evitar que palabras cortas rompan el resaltado de largas
        const sortedKeywords = Array.from(new Set(keywords)).sort((a, b) => b.length - a.length);
        
        sortedKeywords.forEach(word => {
            if (word.length < 3) return; // Evitar resaltar cosas demasiado cortas
            const escapedWord = word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
            // Usamos lookaheads/lookbehinds o límites de palabra para evitar resaltar dentro de HTML
            const wordRegex = new RegExp(`\\b(${escapedWord})\\b`, "gi");
            
            // Lógica para no resaltar dentro de etiquetas ya creadas
            const parts = highlightedText.split(/(<[^>]+>)/g);
            highlightedText = parts.map(part => {
                if (part.startsWith("<")) return part;
                return part.replace(wordRegex, '<span class="highlighted-word">$1</span>');
            }).join("");
        });
    }

    return highlightedText;
}

//Añadir respuesta del asistente con fuentes
function addBotMessage(answer, sources, keywords) {
    const messagesEl = document.getElementById("messages");

    let sourcesHtml = "";
    if (sources && sources.length > 0) {
        let fragmentsHtml = sources.map((s, index) => {
            const contextId = `context-${Date.now()}-${index}`;
            
            // Aplicar resaltados
            const highlightedFragment = applyHighlights(s.fragment, keywords, null);
            const highlightedContext = applyHighlights(s.context, keywords, s.fragment);

            return `
                <div class="source-item">
                    <div class="source-header">
                        <span class="source-speaker">👤 ${s.speaker}</span>
                        <span class="score-badge">${s.score}% Relevancia</span>
                    </div>
                    
                    <div class="source-fragment">
                        "${highlightedFragment}"
                    </div>
                    
                    ${s.context ? `
                        <button class="context-toggle-btn" onclick="document.getElementById('${contextId}').classList.toggle('open')">
                            🔍 Mostrar contexto completo
                        </button>
                        <div id="${contextId}" class="source-context">
                            ${highlightedContext}
                        </div>
                    ` : ""}

                    <div class="source-meta">
                        <span>📅 ${s.date}</span>
                        <span>🏛️ ${s.legislature}</span>
                        <a href="${s.pdf_url}" target="_blank">📄 Diario de Sesiones (PDF)</a>
                    </div>
                </div>
            `;
        }).join("");

        sourcesHtml = `
            <div style="margin-top: 1.5rem; border-top: 1px solid #ddd; padding-top: 1rem;">
                <h4 style="color: #004b8d; margin-bottom: 0.5rem; font-size: 0.9rem;">📚 FUENTES RELACIONADAS</h4>
                <div class="sources-content open">
                    ${fragmentsHtml}
                </div>
            </div>
        `;
    }

    const div = document.createElement("div");
    div.className = "msg";
    div.innerHTML = `
        <div class="msg-avatar bot">🤖</div>
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
                mode: document.getElementById("search-mode").value,
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

        if (data.error) {
            addMessage(` ${data.error}`, "bot");
        } else {
            addBotMessage(data.answer, data.sources, data.keywords);
        }

    } catch (error) {
        loadingDiv.querySelector(".msg-bubble").textContent = "Error al procesar la consulta.";
        console.error("Chat Error:", error);
    }
}
