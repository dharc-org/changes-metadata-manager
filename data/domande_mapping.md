# Mapping cartelle SharePoint → RDF

## 1. Mapping confermati

| Cartella | ID RDF | Descrizione RDF |
|----------|--------|-----------------|
| `S3-PT-DICAM_VetrinaMatriciXilografiche` | `ptb` | Parete con matrici xilografiche |
| `S3-PT-DICAM_Matrice Xilografica Fiore` | `ptb_1` | Matrice xilografica fiore |
| `S3-PT-DICAM_Matrice Xilografica Pianta` | `ptb_2` | Matrice xilografica pianta |
| `S3-PT-DICAM_Matrice Xilografica Serpente` | `ptb_3` | Matrice xilografica serpente |
| `S3-VS6-DBC_Matrice 1 egizia` | `ptb_4` | Matrice xilografica egizia |
| `S5-s.n.-DBC_Busto di Ulisse Aldrovandi` | `s_n` | Busto di Ulisse Aldrovandi |
| `S4-ManicoColtelloZoomorfo` | `50` | Manico in forma di rettile fantastico |
| `S5-CNR-AAltoCentro_TestamentoUlisseAldrovandi` | `a_alto_centro` | Testamento di Ulisse Aldrovandi |
| `S5-B alto destra 1-FICLIT_Mammuthus1` | `b_alto_destra_1` | Mammuthus 1 |
| `S5-B alto destra 1-FICLIT_Mammuthus2` | `b_alto_destra_2` | Mammuthus 2 |

## 2. Pattern senza corrispondenza nell'RDF

| Cartella | Note |
|----------|------|
| `S1-CNR_SoffittoSala1` | Non trovato nell'RDF - da ignorare |

## 3. Ambiguità B basso (fanoni di balena)

Due cartelle SharePoint, un solo identificativo RDF (`b_basso` = "Fanoni di balena"):

- `S5-B basso-DICAM_FanoneBalenaAlto`
- `S5-B basso-DICAM_FanoneBalenaBasso`

**Domanda:** Entrambe le cartelle corrispondono a `b_basso`? O una delle due contiene qualcos'altro?
