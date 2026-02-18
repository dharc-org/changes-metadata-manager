# Piano progetto Aldrovandi - Provenance e pubblicazione Zenodo

## Contesto

Progetto di digitalizzazione 3D della collezione Aldrovandi con l'obiettivo di:
1. Generare file RDF di metadati (`meta.jsonld`) per ogni oggetto (estratti dal TTL esistente)
2. Generare file RDF di provenance (`prov.jsonld`) usando **OpenCitations Data Model** (PROV-O + OCO)
3. Caricare automaticamente su Zenodo le cartelle DCHO e DCHOO
4. Mantenere un mapping path locale → DOI Zenodo

**Scadenza**: Prima di Natale 2025

---

## Risorse disponibili

| Risorsa | Path/URL | Descrizione |
|---------|----------|-------------|
| Metadati oggetti | `aldrovandi_obj.csv` | Oggetti con info descrittive |
| Metadati processi | `aldrovandi_pro.csv` | Pipeline digitalizzazione per oggetto |
| Knowledge Graph esistente | `chad_kg_v2.ttl` | Triple RDF esistenti (CHAD-AP) - **solo metadati, no provenance** |
| Ontologia metadati | https://dharc-org.github.io/chad-ap/current/chad-ap.html | CHAD-AP (CIDOC-CRM based) |
| Ontologia provenance | PROV-O + OpenCitations Ontology (OCO) | Per change tracking |
| Naming convention | `naming_convention.md` | Struttura directory e file |
| Repository SharePoint | https://liveunibo.sharepoint.com/sites/PE5-Spoke4-CaseStudyAldrovandi | File 3D sale 1-6 |

---

## Struttura directory target

```
aldrovandi/
└── sala{1-6}/
    └── {nr_oggetto}/
        ├── raw/
        │   ├── meta.jsonld   → metadati RAW
        │   └── prov.jsonld   → provenance RAW
        ├── rawp/
        │   ├── meta.jsonld   → metadati RAWP + RAW (ereditati)
        │   └── prov.jsonld   → provenance RAWP + RAW
        ├── dcho/
        │   ├── meta.jsonld   → metadati DCHO + RAWP + RAW (ereditati)
        │   └── prov.jsonld   → provenance DCHO + RAWP + RAW
        └── dchoo/
            ├── meta.jsonld   → metadati DCHOO + DCHO + RAWP + RAW (ereditati)
            └── prov.jsonld   → provenance DCHOO + DCHO + RAWP + RAW
```

**4 coppie di file per oggetto**, con contenuto cumulativo secondo le dipendenze.

### Dipendenze tra livelli

```
RAW (no dipendenze)
  ↓
RAWP (dipende da RAW)
  ↓
DCHO (dipende da RAW + RAWP)
  ↓
DCHOO (dipende da RAW + RAWP + DCHO)
```

**Implicazione per gli autori**: Gli autori di DCHOO includono tutti gli autori a cascata delle dipendenze.

---

## Fasi del progetto

### Fase 1: Setup ambiente e analisi dati
- [x] Creare progetto Python con dipendenze
- [x] Analizzare struttura completa dei CSV per mappare tutti i campi
- [x] Parsare il TTL esistente per estrarre pattern di URI e lista entità
- [x] Creare dizionario autori con ORCID (`data/creators_lookup.yaml`, 26 autori)
- [x] Configurare account Zenodo e ottenere API token

### Fase 2: Estrazione metadati (meta.ttl)
- [x] Implementare estrattore di triple dal TTL esistente per entità
- [x] Per ogni oggetto (NR), estrarre tutte le triple correlate dal KG
- [x] Serializzare in `meta.ttl` per cartella oggetto
- [x] Inserire licenza CC0 nei file `meta.ttl`
- [x] Validare metadati generati contro SHACL shapes (`data/shapes-chadap.ttl`)

### Fase 3: Generazione provenance (prov.trig)
- [x] Implementare generatore snapshot PROV-O
  - **Per TUTTE le entità** nel TTL, creare snapshot SE/1
  - [x] `prov:specializationOf` → URI entità
  - [x] `prov:generatedAtTime` → timestamp creazione (da CSV processi)
  - [x] `prov:wasAttributedTo` → ORCID responsible agent
  - [x] `prov:hadPrimarySource` → fonte primaria
  - [x] `prov:description` → "Initial creation"
- [x] Gestire Named Graphs (un graph per snapshot)
- [x] Inserire licenza CC0 nei file `prov.trig`
- [x] Generare file TriG unico con tutta la provenance (da inviare a Ivan)

### Fase 4: Organizzazione file
- [x] Attendere accesso Sharepoint per dati effettivi
- [x] Implementare script per traversare directory e depositare `meta.ttl` + `prov.trig`
- [x] Validare RDF generato (validazione SHACL integrata nel builder)

### Fase 5: Upload Zenodo automatico
- [x] Implementare client API Zenodo (via piccione InvenioRDM API)
  - Autenticazione (token API)
  - Creazione record
  - Upload file
  - Metadata Zenodo da RDF (titolo, autori con ORCID, descrizione, keywords)
  - Pubblicazione record
- [x] Caricare solo oggetti con licenza associata (per ogni sottotipologia RAW, RAWP, DCHO, DCHOO)
- [ ] Generare tabella di associazione entità → DOI Zenodo
- [ ] Compilare tabella CSV di Silvio con informazioni sui documenti caricati su Zenodo
- [ ] Gestire rate limiting e retry logic

### Fase 6: Verifica e documentazione
- [ ] Verificare campione di record Zenodo
- [ ] Documentare processo per riproducibilità

---

## Schema RDF

### meta.jsonld (per oggetto)
Estratto dal TTL esistente (`chad_kg_v2.ttl`), contiene i metadati descrittivi CHAD-AP per l'oggetto.

### prov.jsonld - OpenCitations Data Model (PROV-O + OCO)

Struttura a **Named Graphs** con sistema di **change tracking** via snapshot.

#### URI Pattern
```
{entity_uri}/prov/se/{snapshot_number}
```

Esempio: `https://w3id.org/changes/4/aldrovandi/itm/1/ob00/1/prov/se/1`

#### Struttura snapshot
```turtle
@prefix prov: <http://www.w3.org/ns/prov#> .
@prefix oco: <https://w3id.org/oc/ontology/> .

# Named Graph: {entity_uri}/prov/se/1
GRAPH <https://w3id.org/changes/4/aldrovandi/itm/1/ob00/1/prov/se/1> {

    # Collegamento all'entità descritta
    <https://w3id.org/changes/4/aldrovandi/itm/1/ob00/1/prov/se/1>
        prov:specializationOf <https://w3id.org/changes/4/aldrovandi/itm/1/ob00/1> ;

        # Timestamp creazione
        prov:generatedAtTime "2025-03-24T10:00:00Z"^^xsd:dateTime ;

        # Descrizione dello snapshot
        prov:description "Initial creation of entity metadata" ;

        # Responsible agent (ORCID)
        prov:wasAttributedTo <https://orcid.org/0000-0002-1234-5678> ;

        # Fonte primaria
        prov:hadPrimarySource <https://example.org/source> .
}

# Snapshot successivo (se modificato)
GRAPH <https://w3id.org/changes/4/aldrovandi/itm/1/ob00/1/prov/se/2> {

    <https://w3id.org/changes/4/aldrovandi/itm/1/ob00/1/prov/se/2>
        prov:specializationOf <https://w3id.org/changes/4/aldrovandi/itm/1/ob00/1> ;

        # Derivazione dallo snapshot precedente
        prov:wasDerivedFrom <https://w3id.org/changes/4/aldrovandi/itm/1/ob00/1/prov/se/1> ;

        prov:generatedAtTime "2025-04-01T14:30:00Z"^^xsd:dateTime ;
        prov:description "Updated title metadata" ;
        prov:wasAttributedTo <https://orcid.org/0000-0002-1234-5678> ;

        # Change tracking: SPARQL query con le modifiche
        oco:hasUpdateQuery """
            DELETE DATA {
                <https://w3id.org/changes/4/aldrovandi/itm/1/ob00/1>
                    crm:P102_has_title "Old Title" .
            } ;
            INSERT DATA {
                <https://w3id.org/changes/4/aldrovandi/itm/1/ob00/1>
                    crm:P102_has_title "New Title" .
            }
        """ .
}

# Invalidazione snapshot precedente
GRAPH <https://w3id.org/changes/4/aldrovandi/itm/1/ob00/1/prov/se/1> {
    <https://w3id.org/changes/4/aldrovandi/itm/1/ob00/1/prov/se/1>
        prov:invalidatedAtTime "2025-04-01T14:30:00Z"^^xsd:dateTime .
}
```

#### Proprietà chiave

| Proprietà | Descrizione |
|-----------|-------------|
| `prov:specializationOf` | Collega snapshot all'entità descritta |
| `prov:wasDerivedFrom` | Collega snapshot N a snapshot N-1 |
| `prov:generatedAtTime` | Timestamp creazione snapshot |
| `prov:invalidatedAtTime` | Timestamp invalidazione (quando modificato) |
| `prov:description` | Descrizione testuale delle modifiche |
| `prov:wasAttributedTo` | URI ORCID del responsible agent |
| `prov:hadPrimarySource` | URI della fonte primaria |
| `oco:hasUpdateQuery` | SPARQL INSERT/DELETE DATA con le triple modificate |

---

## Metadati Zenodo (per record)

```json
{
  "metadata": {
    "title": "Titolo oggetto - DCHO/DCHOO",
    "upload_type": "dataset",
    "description": "Digital Cultural Heritage Object from Aldrovandi collection",
    "creators": [
      {"name": "Cognome, Nome", "orcid": "0000-0000-0000-0000", "affiliation": "Istituzione"}
    ],
    "keywords": ["3D model", "cultural heritage", "Aldrovandi"],
    "license": "cc-zero",
    "related_identifiers": [
      {"identifier": "https://doi.org/...", "relation": "isPartOf"}
    ]
  }
}
```

---

## Elementi in attesa

1. ~~**Accesso Sharepoint**~~ - Configurato tramite piccione
2. **Lista ORCID** - ~15 autori da mappare manualmente
3. **Account Zenodo** - Creare account e ottenere API token
4. **Conferma con Sebastian** - Validazione approccio CHAD-AP + OCDM
5. **Tabella CSV da Silvio** - Chiedere a Silvio la tabella CSV con i nomi delle colonne da compilare con le informazioni sui documenti caricati su Zenodo

---

## Note tecniche

### Formato file RDF
- `meta.jsonld`: JSON-LD
- `prov.jsonld`: JSON-LD (supporta Named Graphs)

### Autori nei CSV
Dal CSV processi, gli autori principali sono:
- Alice Bordignon, Sebastian Barzaghi, Arianna Moretti, Arcangelo Massari (metadatazione)
- Federica Bonifazi, Maria Felicia Rega, Federica Collina, etc. (acquisizione/processing)
- Istituzioni: Unibo Ficlit, Unibo Dbc, CNR ISPC, Unibo Dicam
