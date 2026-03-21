<!--
SPDX-FileCopyrightText: 2025-2026 Arcangelo Massari <arcangelomas@gmail.com>

SPDX-License-Identifier: ISC
-->

# Mapping cartelle SharePoint → RDF

## 1. Mapping confermati

Tutti i mapping sono definiti in `FOLDER_TO_ID` nel file `folder_metadata_builder.py`.

### Mapping speciali

| Cartella | ID RDF | Descrizione |
|----------|--------|-------------|
| `S3-PT-DICAM_VetrinaMatriciXilografiche` | `ptb` | Parete con matrici xilografiche |
| `S3-PT-DICAM_Matrice Xilografica Fiore` | `ptb_1` | Matrice xilografica fiore |
| `S3-PT-DICAM_Matrice Xilografica Pianta` | `ptb_2` | Matrice xilografica pianta |
| `S3-PT-DICAM_Matrice Xilografica Serpente` | `ptb_3` | Matrice xilografica serpente |
| `S3-VS6-DBC_Matrice 1 egizia` | `ptb_4` | Matrice xilografica egizia |
| `S5-s.n.-DBC_Busto di Ulisse Aldrovandi` | `s_n` | Busto di Ulisse Aldrovandi |
| `S4-ManicoColtelloZoomorfo` | `50` | Manico in forma di rettile fantastico |
| `S5-CNR-AAltoCentro_TestamentoUlisseAldrovandi` | `a_alto_centro` | Testamento di Ulisse Aldrovandi |

### Manoscritti

Mapping derivato da `crm:P3_has_note` nel KG:

| Cartella | ID RDF | Titolo nella nota |
|----------|--------|-------------------|
| `S5-Manoscritto-FICLIT_AdnotationesVariaePraesertimDeAnimalibus` | `m1` | Adnotationes variae praesertim de animalibus |
| `S5-Manoscritto-FICLIT_VulgataProverbia` | `m2` | Vulgata proverbia |
| `S5-Manoscritto-FICLIT_PandechionEpistemonicon` | `m3` | Pandechion epistemonicon |
| `S5-Manoscritto-FICLIT_LexiconRerumInanimatarum` | `m4` | Lexicon rerum inanimatarum |
| `S5-Manoscritto-FICLIT_BibliothecaSecundumNominaAuthorum` | `m5` | Bibliotheca secundum nomina authorum |
| `S5-Manoscritto-FICLIT_TheatrumBiblicumNaturale` | `m6` | Theatrum biblicum naturale |
| `S5-Manoscritto-FICLIT_LibroDeiVisitatori` | `m7` | Libro dei visitatori |
| `S5-Manoscritto-FICLIT_DiscorsoNaturaleAldrovandi` | `m8` | Discorso naturale di Ulisse Aldrovandi |

### Posizioni A/B e vetrine

Tutte le 10 posizioni A/B e le 113 vetrine sono mappate esplicitamente in `FOLDER_TO_ID`.

## 2. Cartelle ignorate

| Cartella | Motivo |
|----------|--------|
| `S1-CNR_SoffittoSala1` | I soffitti non hanno entità nel KG |
| `S5-B basso-DICAM_FanoneBalenaAlto` | Dati di acquisizione inutilizzabili |
| `materials` | Cartella di sistema |
| `sala 4` | Cartella duplicata in Sala4 |

## 3. Note

### 3.1 Note sulle cartelle

Nota: `27a-f` e `74a-e` esistono nel KG con suffisso, quindi hanno mapping 1:1.

### 3.2 Storico unificazioni (febbraio 2026)

- Le cartelle `S6-98a/b/c-DA-Calchi facciali colorati, boscimani` sono state unificate in `S6-98-DA-Calchi facciali colorati, boscimani`
- Le cartelle `S6-111a/b-DA-Fossile, Dalmanites sp. RECTO/VERSO` sono state unificate in `S6-111-DA-Fossile, Dalmanites sp`
- Gli ID 111 e 113 sono stati invertiti nelle tabelle metadati (111 = Dalmanites, 113 = Cambropallas)
