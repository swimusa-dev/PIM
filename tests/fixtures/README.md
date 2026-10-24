# Test fixtures (spec 1.4)

Anonymized, hand-built samples that reproduce the shapes found in the three real files reviewed in v1.1.
No real cost, UPC, or copy data is included.

| File | Stands in for | Findings it exercises |
|---|---|---|
| `style_master_sample.csv` | BlueCherry Style Master export (Delta table `swim_data_whse.bluecherry.style_master`) | F2 placeholders, F3 blanket defaults, F6 inconsistent option spellings and test values, F7 identifier formats, F8 combined sizes and a prepack with no size, F9 Division and TARGET VITAMIN A, F12 repeat body / new color, discontinued style |
| `shopify_products_export.csv` | Shopify product CSV export of the Vitamin A store | EXP-13 snapshot by CSV upload, protected recommendation metafields (D-09), variants by SKU |
| `air_filenames.txt` | Filenames and tags of Air assets | IMG-03 tiers 1 and 2, unparsed queue |
| `setup_file_sample.csv` | VA Product Information Setup File (two header rows, no identifiers) | IMP-01 parser, IMP-05 keyless mode (Phase 2) |
