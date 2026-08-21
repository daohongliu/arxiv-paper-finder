You are extracting author affiliation metadata from the first page of an arXiv paper.

RAW TEXT (may contain OCR-like artifacts, headers, footnotes):
<<<
{{paper_text}}
>>>

AUTHOR NAMES FROM METADATA (order as listed on arXiv):
{{author_names}}

Task: for each author, determine their institution and whether it is in mainland China. Then give an overall judgment on whether this paper plausibly has any mainland-China involvement.

1. List every author in the order they appear, matching the metadata list where possible.
2. If the text links authors to affiliations with superscripts/symbols/numbers, resolve the mapping. A shared affiliation applies to every author it marks.
3. For each author give the normalized institution name, the country, and the mainland_china verdict.

Mainland China policy:
- "Mainland China" = institutions located in the People's Republic of China, INCLUDING Hong Kong and Macau (e.g. Tsinghua University, Peking University, Chinese Academy of Sciences / CAS, BAAI, Shanghai AI Laboratory, Tsinghua Shenzhen International Graduate School, University of Hong Kong, CUHK, HKUST, Hong Kong Polytechnic University, City University of Hong Kong, University of Macau, Macau University of Science and Technology).
- Institutions in Taiwan are NOT mainland China (e.g. Academia Sinica, National Taiwan University, National Tsing Hua University are not mainland).
- If an author has multiple affiliations, mainland_china is "yes" if ANY of them is mainland.
- Joint appointments: judge by what the paper itself states; do not invent affiliations from author names alone.

Look HARD for affiliation evidence — it is often indirect:
- Affiliations may appear in footnotes, page-bottom notes, equal-contribution/work-done-while lines, or correspondence lines instead of under the author names.
- Email addresses are strong evidence: scan the whole text for emails. Domain patterns identify institutions: @*.edu.cn = a Chinese university (e.g. xn-ing@seu.edu.cn = Southeast University); @*.ac.cn = Chinese Academy of Sciences system; @pku.edu.cn = Peking University; @baai.ac.cn = BAAI; @pjlab.org.cn = Shanghai AI Laboratory; @*.edu.hk / @*.org.hk (Hong Kong) and @*.edu.mo / @*.mo (Macau) also count as mainland for our purposes. An email like zhangwei@xxx.edu.cn proves that author's mainland-China affiliation.
- Funding and grant lines are evidence: NSFC / National Natural Science Foundation of China, MOST / Ministry of Science and Technology, Chinese provincial/municipal science programs, or grants from Chinese universities indicate mainland involvement.
- Abbreviations count (e.g. "CAS", "SJTU", "HKUST").

Then judge likely_mainland_china for the paper as a whole. This is a RECALL-oriented screening decision, so err generously on the side of "yes":
- Set "yes" if ANY concrete evidence points to mainland involvement (an affiliation, email domain, or funding body as above).
- Also set "yes" when no affiliation is visible at all but mainland involvement is merely plausible — for example when several author names look Chinese (pinyin-style family + given names, e.g. Wenzhe Xu, Yiyang Sun, Xiaoming Zhang). Chinese personal names alone are enough to say "yes" here.
- Set "yes" whenever you are unsure. Only set "no" when you are confident the paper has no mainland-China involvement (e.g. all identifiable names, emails, and institutions point to other countries).

Rules for per-author fields:
- Use ONLY information present in the provided text. If no affiliation is visible for an author, set institution to "" and mainland_china to "unclear".
- If you cannot determine the country of an institution, use "unclear" for both country and mainland_china.
- The likely_mainland_china judgment may use weaker evidence (such as author names) than the per-author fields.

Return ONLY a JSON object with exactly this schema — nothing else, no extra fields:
{
  "likely_mainland_china": "yes" | "no",
  "authors": [
    {
      "name": "string",
      "institution": "string",
      "country": "string",
      "mainland_china": "yes" | "no" | "unclear"
    }
  ]
}
