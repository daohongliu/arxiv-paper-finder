You are extracting author affiliation metadata from the first page of an arXiv paper.

RAW TEXT (may contain OCR-like artifacts, headers, footnotes):
<<<
{{paper_text}}
>>>

AUTHOR NAMES FROM METADATA (order as listed on arXiv):
{{author_names}}

Task:
1. List every author in the order they appear, matching the metadata list where possible.
2. For each author, record their affiliation(s) exactly as printed on the page. Shared affiliations must be repeated per author. If the text links authors to affiliations with superscripts/symbols/numbers, resolve the mapping.
3. For each author decide whether they are affiliated with a MAINLAND CHINA institution.

Mainland China policy:
- "Mainland China" = institutions located in the mainland of the People's Republic of China (e.g. Tsinghua University, Peking University, Chinese Academy of Sciences / CAS, BAAI, Shanghai AI Laboratory, Tsinghua Shenzhen International Graduate School).
- Institutions in Hong Kong, Macau, or Taiwan are NOT mainland China (e.g. University of Hong Kong, CUHK, HKUST, Academia Sinica are not mainland).
- If an author has multiple affiliations, mainland_china is "yes" if ANY of them is mainland.
- Joint appointments: judge by what the paper itself states; do not invent affiliations from author names alone.

Rules:
- Use ONLY information present in the provided text. If no affiliation is visible for an author, set affiliation_raw to "" and mainland_china to "unclear".
- If you cannot determine the country of an institution, use "unclear".
- Set "institution" to the normalized short institution name (e.g. "Tsinghua University"), and "country" to the country name.

Return ONLY a JSON object with exactly this schema:
{
  "authors": [
    {
      "name": "string",
      "affiliation_raw": "string",
      "institution": "string",
      "country": "string",
      "mainland_china": "yes" | "no" | "unclear",
      "note": "string (optional reasoning, keep short)"
    }
  ],
  "notes": "string (any parsing caveats)"
}
