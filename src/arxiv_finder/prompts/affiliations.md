You are extracting author affiliation metadata from the first page of an arXiv paper.

RAW TEXT (may contain OCR-like artifacts, headers, footnotes):
<<<
{{paper_text}}
>>>

AUTHOR NAMES FROM METADATA (order as listed on arXiv):
{{author_names}}

Task: for each author, determine their institution and whether it is in mainland China.

1. List every author in the order they appear, matching the metadata list where possible.
2. If the text links authors to affiliations with superscripts/symbols/numbers, resolve the mapping. A shared affiliation applies to every author it marks.
3. For each author give the normalized institution name, the country, and the mainland_china verdict.

Mainland China policy:
- "Mainland China" = institutions located in the People's Republic of China, INCLUDING Hong Kong and Macau (e.g. Tsinghua University, Peking University, Chinese Academy of Sciences / CAS, BAAI, Shanghai AI Laboratory, Tsinghua Shenzhen International Graduate School, University of Hong Kong, CUHK, HKUST, Hong Kong Polytechnic University, City University of Hong Kong, University of Macau, Macau University of Science and Technology).
- Institutions in Taiwan are NOT mainland China (e.g. Academia Sinica, National Taiwan University, National Tsing Hua University are not mainland).
- If an author has multiple affiliations, mainland_china is "yes" if ANY of them is mainland.
- Joint appointments: judge by what the paper itself states; do not invent affiliations from author names alone.

Affiliation evidence can be indirect — use it:
- Affiliations may appear in footnotes, page-bottom notes, or correspondence lines instead of under the author names.
- Email domains are affiliation evidence: a correspondence/author email like xn-ing@seu.edu.cn identifies Southeast University (mainland China); @pku.edu.cn = Peking University; @*.ac.cn = Chinese Academy of Sciences system; @*.edu.cn = a Chinese university; @baai.ac.cn = BAAI. Use such domains to assign the institution and mainland_china for the corresponding author.
- Abbreviations count too (e.g. "CAS", "SJTU", "HKUST").

Rules:
- Use ONLY information present in the provided text. If no affiliation is visible for an author, set institution to "" and mainland_china to "unclear".
- If you cannot determine the country of an institution, use "unclear" for both country and mainland_china.

Return ONLY a JSON object with exactly this schema — nothing else, no extra fields:
{
  "authors": [
    {
      "name": "string",
      "institution": "string",
      "country": "string",
      "mainland_china": "yes" | "no" | "unclear"
    }
  ]
}
