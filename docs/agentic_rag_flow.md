# Flujo de RAG Agéntico DiSeCan

Este diagrama representa la arquitectura actual del sistema, integrando las técnicas de **HyDE**, **Expansión Léxica** y **Re-rankeo Contextual**.

```mermaid
graph TD
    User([<b>Consulta de Usuario</b>]) --> QA[<b>QueryAnalyzer LLM</b>]
    
    subgraph "Análisis Agéntico"
        QA --> Plan{<b>Search Plan</b>}
        Plan -->|Genera| HyDE[<b>Párrafo HyDE: Respuesta Hipotética</b>]
        Plan -->|Extrae| Expansion[<b>Diccionario de Intenciones: Sinónimos</b>]
    end

    subgraph "Recuperación Híbrida"
        HyDE --> Vector[<b>Búsqueda Semántica ChromaDB</b>]
        Expansion --> Lemmatizer[<b>Servicio de Lematización</b>]
        Lemmatizer --> SQL[<b>Búsqueda Léxica SQL DiSeCan</b>]
        
        Vector --> RRF[<b>Reciprocal Rank Fusion</b>]
        SQL --> RRF
    end

    subgraph "Refinamiento y Síntesis"
        RRF --> Reranker[<b>LLM Reranker: Filtro de Relevancia</b>]
        Reranker --> Synthesizer[<b>Synthesizer LLM: Generación de Respuesta</b>]
        Synthesizer --> Final([<b>Respuesta + Citaciones + Highlights</b>])
    end
    
    style User fill:#E1F5FE,stroke:#01579B,stroke-width:2px
    style Final fill:#E8F5E9,stroke:#2E7D32,stroke-width:2px
    style QA fill:#FFF9C4,stroke:#FBC02D,stroke-width:2px
    style Reranker fill:#F3E5F5,stroke:#7B1FA2,stroke-width:2px
    style HyDE fill:#E0F2F1,stroke:#00695C,stroke-width:2px
    style Expansion fill:#E0F2F1,stroke:#00695C,stroke-width:2px
    style Synthesizer fill:#FFF3E0,stroke:#E65100,stroke-width:2px
    style Plan fill:#FFFFFF,stroke:#333333,stroke-dasharray: 5 5
```

## Componentes Clave

- **HyDE (Hypothetical Document Embeddings)**: Convierte una pregunta abstracta en un párrafo que "suena" como una intervención parlamentaria, mejorando drásticamente el matching semántico.
- **Expansión Léxica**: El LLM actúa como traductor de lenguaje natural a lenguaje técnico parlamentario (ej: de "barato" a "flete", "carestía", "subvención").
- **Re-rankeo LLM**: Una vez recuperados los fragmentos, un modelo pequeño (Qwen 3B) evalúa la relevancia real de cada uno antes de mostrarlos al usuario, reduciendo el ruido.
