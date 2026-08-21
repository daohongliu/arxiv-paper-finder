"""Cheap, deliberately LAX heuristic: exclude a paper only when it is very
clear that none of its authors could plausibly be Chinese.

We match author-name tokens against a large list of romanized Chinese
surnames (Mandarin pinyin, Wade-Giles, Cantonese, Hokkien/Teochew/Hakka,
Singapore/Malaysia romanizations). False positives (papers we keep
unnecessarily) are fine; false negatives (Chinese-authored papers we drop)
are not. Any uncertainty keeps the paper.
"""
from __future__ import annotations

import re
import unicodedata

_SINGLE = """
wang li zhang liu chen yang huang zhao wu zhou xu sun ma zhu hu guo he gao
lin luo zheng liang xie song tang feng han cao zeng peng dong xiao tian yuan
pan jiang cai yu du ye cheng wei su lu ding ren shen yao tan qian dai shi jia
zou xiong meng qin guan lai qu shang zhuo ning fu bi hao jin qi jing gu zhan
ji hua geng yun lei ni sheng zha mu lan yin bai shui dou bao zhen xia wen liao
chi zhuang mou bu sha xin zong shan cui kang mao qiu niu yan huan xiang pei
lian ke jun shu xun ju yong neng pu zang ruan ying yue zhang hao xuan cen gou
pi bing jiao kuai le liang lou juan min ou tong zhai zhong zu zuan an ao ban
bang bei ben bi bing bo cai can cang ce chai chan chang chao che shen chi chong
chou chu chuang ci cong cu cuan da dan dang dao de deng di diao dong dou duan
dun duo e en er fa fan fang fei fen feng fo fou fu gai gan gang ge gen
gong gou gu gua guai guan guang gui gun guo ha hai han hang heng hong hou huai
hui hun huo jian jiao jie jin jiong jiu ju juan jue kai kan keng kong kou ku
kua kuai kuan kui kun kuo lang lao le leng lian liao lie ling long lou luan lun
lv lve mai man mang mei men mi mian miao mie min ming miu mo mou nai nan nao
nei nen neng nian niang nie nin ning nong nou nu nuan nue nuo ou pai pang pao
pei pen pian piao pin ping po pou pu qi qia qian qiang qiao qie qing qiong
qiu qu quan que rang rao ren reng ri rong rou ru ruan rui run ruo sa sai san
sang sao se sen sha shai shan shao she shen sheng shi shou shu shua shuai
shuan shuang shui shun shuo si song sou su suan sui sun suo ta tai tan tao te
teng ti tiao tie ting tong tou tu tuan tui tun tuo wa wai wan wang wei
weng wo xi xian xiang xie xin xing xiu xu xue xun ya yan yang ye yi yin ying
yo yong you youn yuan yue za zai zan zang ze zei zen zeng zha zhai zhan zhang
zhao zhe zhen zheng zhi zhong zhou zhu zhua zhuai zhuan zhuang zhui zhun zhong
zi zong zu zuan zui zun zuo
wong chan lee leung lam ho tsang fung kwok cheung tung yau mak ng lau tam yip
kwong tsai chow law lok sit chung kwan wan yuen pun lo sin yiu ngai kong hung
chong kam cheng tseng tsai hsu chiang chou chao kuo yeh chi tso teng chu hsieh
ong lim goh chua yeo koh teo chai sim loo foo yap loh low fong pang pua quek
tay teng teoh tiong yeoh yeow yong seow siah soh wee wun hng koo cheong chee
choo thio kwek leong mok gan heng leo liaw loke lye mah oo ong poh see thng
too ung woo yam yow yun gim phee qua poo kow
lyu lui chau chern hei ba baa hooi
""".split()

_COMPOUND = """
ouyang sima shangguan zhuge situ huangfu zhangsun yuchi murong dugu gongsun
linghu tuoba helu zhongsun yuwen zhangsun
""".split()

SURNAMES = set(_SINGLE) | set(_COMPOUND)

_CJK = re.compile(r"[\u4e00-\u9fff]")


def _tokens(name: str) -> list[str] | None:
    """Normalize a name to lowercase alpha tokens; None if clearly not latin."""
    if _CJK.search(name):
        return None
    s = unicodedata.normalize("NFKD", name)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower().replace("-", " ").replace(".", " ").replace("'", " ")
    return re.findall(r"[a-z]+", s)


def name_plausibly_chinese(name: str) -> bool | None:
    """True = plausibly Chinese; False = personal name, no Chinese marker;
    None = cannot judge (single token, initials, org-like) -> keep."""
    toks = _tokens(name)
    if toks is None:  # contains CJK characters -> treat as Chinese
        return True
    if len(toks) < 2 or any(len(t) > 14 for t in toks):
        return None
    for t in toks:
        if t in SURNAMES:
            return True
    # joined bigram check for compound surnames like "ouyang" written as "ou yang"
    joined = "".join(toks)
    return any(c in joined for c in _COMPOUND)


def any_plausible_chinese_author(names: list[str]) -> bool:
    """LAX paper-level check: only False when every author has a clearly
    personal, clearly non-Chinese name."""
    if not names:
        return True  # no author info -> keep, be safe
    uncertain = False
    for n in names:
        r = name_plausibly_chinese(n)
        if r is True:
            return True
        if r is None:
            uncertain = True
    return uncertain
