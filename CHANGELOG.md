# Changelog

## 0.9b2

- Added `DARKLAND.ALC` parsing, writing, and validation support.
- Added a linked `Alchemy` tab to the `Items, Saints, Formulae & Alchemy` editor.
- Added alchemy ingredient validation against `DARKLAND.LST` item codes.
- Added low-level `MSGFILES` archive inspection with entry index, raw field `0x0C`, size, and offset metadata in the dialog editor.
- Added confirmed structural validation checks for `MSGFILES`, `DARKLAND.LOC`, and selected `CTY` consistency rules.
- Added direct `Open in Tool` routing from CAT entries into the appropriate DARK editor for known archive formats.
- Expanded validation issue navigation so related `ALC` and `MSG/MSGFILES` findings can jump straight into the corresponding editor content.
- Added in-editor validation badges and scoped `Issues...` actions across the main structured editors.
- Added per-record issue markers in enemy, city, formula, alchemy, and MSG card lists so affected rows are visibly flagged.
- Corrected the city-contents fortress label from `no fortress` to `fortress` after a stock-data audit of `DARKLAND.CTY`.
- Updated format coverage so `DARKLAND.ALC` is now marked as editable.
- Renamed public `WIP` tooling labels to `Research` for a cleaner public-facing UI.
- Cleaned the public repo presentation, including README encoding fixes and removal of old vendor demo/debug entry points.
- Updated the in-app About dialog credits to include M. Gutsohn (Nurnberg project) for additional file-format information.
- Improved local release workflow support for the standalone DARK repo.
- Clarified the dialog-editor `MSGFILES` metadata panel so the `0x0C` archive field is explicitly labeled as unknown/raw.

## 0.9b

- Initial public DARK beta release.
- Included structured editors for saves, cities, locations, descriptions, items, saints, formulae, enemies, and dialog/message data.
- Included PIC, IMC, CAT, font, and DGT tooling.
- Included validation, coverage reporting, KB note viewing, and research placeholders for WIP formats.
