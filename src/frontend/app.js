// Estado de la búsqueda
let isSearching = false;

// ── Búsqueda ─────────────────────────────────────────────────────────────────
async function performSearch(event) {
    event.preventDefault();
    if (isSearching) return;

    const inputEl = document.getElementById("search-input");
    const modeEl = document.getElementById("search-mode");
    
    // Filtros
    const legislature = document.getElementById("filter-legislature").value;
    const date = document.getElementById("filter-date").value;
    const speaker = document.getElementById("filter-speaker").value;

    const query = inputEl.value.trim();
    if (!query) return;

    // UI Updates
    isSearching = true;
    document.getElementById("results-section").style.display = "block";
    document.getElementById("loading-indicator").style.display = "block";
    document.getElementById("ai-answer-container").style.display = "none";
    document.getElementById("sources-list").innerHTML = "";
    document.getElementById("results-header").style.display = "none";

    const payload = {
        query: query,
        mode: modeEl.value,
        filters: {}
    };

    if (legislature) payload.filters.legislatura = legislature;
    if (date) payload.filters.fecha = date;
    if (speaker) payload.filters.orador = speaker;

    try {
        const response = await fetch("/api/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });

        const data = await response.json();
        
        document.getElementById("loading-indicator").style.display = "none";

        if (!response.ok) {
            showError(data.error || "Error de red.");
            return;
        }

        renderResults(data);

    } catch (error) {
        document.getElementById("loading-indicator").style.display = "none";
        showError("No se pudo conectar con el servidor: " + error.message);
    } finally {
        isSearching = false;
    }
}

// ── Renderizado ──────────────────────────────────────────────────────────────
function renderResults(data) {
    const { answer, sources, keywords, mode } = data;

    // 1. Mostrar IA (solo si no es modo lingüístico estricto y hay respuesta)
    if (mode === "full" && answer) {
        document.getElementById("ai-answer-container").style.display = "block";
        document.getElementById("ai-answer-content").innerHTML = marked.parse(answer);
        
        const kwContainer = document.getElementById("ai-keywords");
        kwContainer.innerHTML = "<strong>Términos extraídos:</strong> " + 
            (keywords && keywords.length > 0 
                ? keywords.map(kw => `<span class="keyword-tag">${kw}</span>`).join("")
                : "Ninguno");
    }

    // 2. Cabecera de resultados
    const header = document.getElementById("results-header");
    header.style.display = "block";
    const countSpan = document.getElementById("results-count");
    
    if (!sources || sources.length === 0) {
        countSpan.innerHTML = "No se encontraron coincidencias para la búsqueda.";
        return;
    }
    
    countSpan.innerHTML = `Mostrando ${sources.length} fragmentos recuperados.`;

    // 3. Lista de Fragmentos
    const listContainer = document.getElementById("sources-list");
    
    sources.forEach((src, idx) => {
        const item = document.createElement("div");
        item.className = "source-item";

        let fragmentHtml = src.fragment || "";
        let contextHtml = src.context || "";

        // Subrayar el fragmento dentro del contexto ANTES de resaltar palabras clave
        if (contextHtml && fragmentHtml) {
            // Escapar regex
            const escapeRegExp = (str) => str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
            // Intentar buscar la frase literal exacta dentro del párrafo para subrayarla
            const fragmentPattern = new RegExp(escapeRegExp(fragmentHtml), 'g');
            if (fragmentPattern.test(contextHtml)) {
                contextHtml = contextHtml.replace(fragmentPattern, '<span class="underlined-sentence">$&</span>');
            }
        }

        // Resaltar palabras clave en el fragmento y el contexto
        fragmentHtml = highlightKeywords(fragmentHtml, keywords);
        contextHtml = highlightKeywords(contextHtml, keywords);

        // Reemplazar saltos de línea por <br>
        fragmentHtml = fragmentHtml.replace(/\n/g, '<br>');
        contextHtml = contextHtml.replace(/\n/g, '<br>');
        
        item.innerHTML = `
            <div class="source-score">${src.score}%</div>
            <div class="source-fragment">${fragmentHtml}</div>
            <div class="source-meta">
                — DIARIO DE SESIONES [${src.legislature || 'Legislatura desc.'}] | ${src.speaker} | ${src.date}
            </div>
            ${src.context ? `
                <button class="context-toggle-btn" onclick="toggleContext('ctx-${idx}')">Ver contexto completo</button>
                <div id="ctx-${idx}" class="source-context">
                    ${contextHtml}
                </div>
            ` : ""}
        `;
        listContainer.appendChild(item);
    });
}

// Helper para resaltar palabras clave sin romper el HTML y tolerando acentos
function highlightKeywords(htmlString, keywords) {
    if (!keywords || keywords.length === 0) return htmlString;
    
    // Filtrar palabras muy cortas y ordenar por longitud descendente
    const sortedKws = keywords
        .filter(k => k.length > 2)
        .sort((a, b) => b.length - a.length);
    
    if (sortedKws.length === 0) return htmlString;

    const escapeRegExp = (str) => str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    
    // Convertir vocal a una clase regex que acepte con o sin tilde
    const makeAccentInsensitive = (str) => {
        return escapeRegExp(str)
            .replace(/a/gi, '[aáAÁ]')
            .replace(/e/gi, '[eéEÉ]')
            .replace(/i/gi, '[iíIÍ]')
            .replace(/o/gi, '[oóOÓ]')
            .replace(/u/gi, '[uúUÚüÜ]');
    };

    let result = htmlString;
    
    for (const kw of sortedKws) {
        const basePattern = makeAccentInsensitive(kw);
        // Construimos un regex que admita sufijos comunes (s, es, mente, os, as)
        // y que use (?![^<]*>) para evitar romper atributos HTML como class="..."
        // Usamos un boundary flexible (^|\s|[>.,!?;:'"()/-]) y lo mismo al final
        // para asegurarnos de no cazar partes en medio de otras palabras largas,
        // pero \b en JS no funciona bien con caracteres acentuados, así que hacemos esto:
        
        const pattern = new RegExp(`(^|\\s|[>.,!?;:'"()\\/-])(${basePattern}(?:s|es|mente|os|as)?)(?=[\\s<.,!?;:'"()\\/-]|$)`, 'gi');
        
        // Reemplazamos manteniendo el prefijo ($1) y envolviendo la coincidencia ($2)
        result = result.replace(pattern, '$1<span class="highlighted-word">$2</span>');
    }
    return result;
}

function toggleContext(id) {
    const ctx = document.getElementById(id);
    if (ctx.classList.contains("open")) {
        ctx.classList.remove("open");
    } else {
        ctx.classList.add("open");
    }
}

function showError(msg) {
    document.getElementById("results-header").style.display = "block";
    document.getElementById("results-count").innerHTML = `<span style="color:red; font-weight:bold;">Error:</span> ${msg}`;
}
