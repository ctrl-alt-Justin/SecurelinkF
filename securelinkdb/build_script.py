# -*- coding: utf-8 -*-
import os

sections = {}

sections['COMMON GREETINGS & CONVERSATIONAL FILLERS'] = [
    'kumusta', 'kumusta ka', 'kumusta ka na', 'kumusta po', 'kumusta kayo',
    'magandang araw', 'magandang araw po', 'magandang umaga', 'magandang umaga po',
    'magandang hapon', 'magandang hapon po', 'magandang gabi', 'magandang gabi po',
    'oo nga', 'oo nga pala', 'sige na', 'sige na nga', 'talaga', 'talaga ba', 'talaga naman',
    'naman', 'kasi', 'kasi naman', 'eh', 'ano ba', 'ano ba yan', 'ah oo', 'ay nako', 'nako', 'naku po',
    'syempre', 'syempre naman', 'siguro', 'siguro nga', 'parang', 'parang ganun', 'medyo',
    'ganoon', 'ganoon ba', 'ganyan', 'ganyan nga', 'ganito', 'ganito kasi', 'diba', 'di ba',
    'kaya nga', 'e di', 'edi', 'edi wow', 'palibhasa', 'samantalang', 'imbis na', 'upang',
    'dahil sa', 'baka sakali', 'di umano', 'daw', 'raw', 'rin', 'din', 'man', 'pati', 'maski',
    'muna', 'naman pala', 'tuloy', 'sana naman', 'kaya pala', 'basta'
]

sections['COMMON PHRASES & DAILY QUESTIONS'] = [
    'anong ginagawa mo', 'anong nangyari', 'anong balita sayo', 'anong oras na',
    'sino ka', 'sino yan', 'sino ba yun', 'sinong kasama mo', 'sinong nagturo sayo',
    'saan ka pupunta', 'saan ka galing', 'saan tayo pupunta', 'saang banda yun',
    'kailan pa', 'kailan tayo aalis', 'kailan ang pasahan', 'kailan ka uuwi',
    'bakit ganyan', 'bakit ka ganyan', 'bakit hindi', 'bakit ngayon ka lang',
    'paano mo nagawa', 'paano ba ito', 'paano pumunta doon', 'paano mo nalaman',
    'tara na', 'tara kain', 'tara na kain tayo', 'tara sabay na tayo', 'halika na', 'halika rito',
    'huwag na', 'wag na', 'sige', 'sige mauna ka na', 'okay lang', 'okay lang ako',
    'hindi ko alam', 'ewan ko', 'ewan ko sayo', 'di ko alam', 'wala akong alam dyan',
    'pwede ba', 'pwede po ba', 'paki naman', 'pakiusap', 'pakiusap lang',
    'salamat', 'maraming salamat', 'salamat po', 'walang anuman', 'walang anuman po',
    'pasensya na', 'sorry na', 'paumanhin po', 'tuloy po kayo', 'upo ka muna',
    'anong pangalan mo', 'taga saan ka', 'ilang taon ka na', 'kumain ka na ba',
    'ano pong kailangan niyo', 'may maitutulong ba ako', 'saan mo nilagay',
    'nakita mo ba gamit ko', 'sandali lang po', 'antayin mo ako saglit',
    'ingat ka sa byahe', 'tawagan mo ako mamaya', 'magkita tayo bukas'
]

sections['DISCOURSE & EMOTIONAL SLANG'] = [
    'eme', 'eme lang', 'char', 'charot', 'char lang', 'marites', 'marites ka talaga',
    'omsim', 'omsim pre', 'legit', 'legit ba yan', 'solid', 'solid naman niyan',
    'taray', 'taray mo naman', 'sakalam', 'sakalam talaga', 'lodi', 'lodi kita',
    'petmalu', 'petmalu mo', 'forda', 'forda person', 'sus', 'jusko', 'susmaryosep',
    'hala', 'hala ka', 'hoy', 'hoy ka', 'uy', 'aray', 'aray ko', 'aba', 'aba naman',
    'naku', 'naku po', 'ge', 'sge', 'taralets', 'chika', 'chika mo naman',
    'nakakainis', 'nakakabaliw', 'nakakagulat', 'nakakatuwa', 'nakakaiyak', 'nakakakilig',
    'grabe', 'grabe naman', 'sobrang ganda', 'sobrang pangit', 'super pangit', 'super ganda',
    'ang dami mo namang alam', 'ang sama mo naman', 'joke lang', 'seryoso ako',
    'hindi joke', 'totoo ito', 'mali ka dyan', 'tama ako', 'bida-bida ka na naman',
    'pabibo kay maam', 'sipsip sa teacher', 'epal ka dyan', 'walang basagan ng trip',
    'wag kang mag-inarte', 'nakakahiya sobra', 'cringe malala', 'ghosting malala',
    'toxic mo naman', 'chill ka lang muna', 'wag kang praning', 'spill the tea',
    'dasurv mo yan', 'sana all', 'main character vibes', 'ramdam kita pre'
]

sections['ENGINEERING, SYSTEMS & DEV TAGLISH'] = [
    'paki-compile', 'nakacompile', 'naka-deploy', 'nakadeploy', 'nag-crash', 'nagcrash',
    'nag-error', 'nagerror', 'paki-push', 'pakipush', 'na-pull', 'napull',
    'nag-conflict', 'nagconflict', 'i-debug', 'idebug', 'naka-local', 'nakalocal',
    'paki-solder', 'pakisolder', 'naka-ground', 'nakaground', 'nag-short', 'nagshort',
    'i-wire', 'iwire', 'naka-loop', 'nakaloop', 'nag-trigger', 'nagtrigger',
    'paki-check yung code', 'i-run mo', 'irun mo', 'naka-server', 'nakaserver',
    'nag-restart', 'nagrestart', 'i-restart', 'irestart', 'na-save', 'nasave',
    'paki-save', 'pakisave', 'naka-database', 'i-connect', 'iconnect',
    'naka-connect', 'nakaconnect', 'na-disconnect', 'nadisconnect', 'paki-test',
    'pakitest', 'i-test', 'itest', 'naka-live', 'nakalive', 'nag-hang', 'naghang',
    'nag-lag', 'naglag', 'paki-message', 'i-forward', 'iforward', 'i-download', 'idownload',
    'naka-on', 'naka-off', 'naka-mute', 'i-unmute', 'paki-screenshot', 'i-clear mo cache',
    'mahina wifi signal', 'lowbat na ako', 'pahiram powerbank', 'i-plug sa outlet'
]

sections['GAMING, ESPORTS & CO-OP TAGLISH'] = [
    'paki-gank', 'pakigank', 'naka-ulti', 'nakaulti', 'pa-heal', 'paheal',
    'i-revive', 'irevive', 'paki-revive', 'pakirevive', 'na-dc', 'nadc',
    'paki-drop', 'pakidrop', 'pa-carry', 'pacarry', 'nag-feed', 'nagfeed',
    'tara roshan', 'tara push', 'i-stun mo', 'istun mo', 'relic run',
    'pa-farm', 'pafarm', 'naka-bkb', 'nakabkb', 'naka-steel path', 'tara laro',
    'i-party mo ko', 'iparty mo ko', 'game na', 'ready na', 'go na', 'laban tayo',
    'ayaw ko na', 'gg na', 'good game', 'nice one', 'bobo gank', 'wag mag feed',
    'paki def', 'pakidef', 'i-defend', 'idefend', 'naka-cooldown', 'naka cd',
    'walang mana', 'ubos mana', 'pa-buff', 'pabuff', 'i-loot mo', 'iloot mo',
    'tara rank game', 'one on one sa mid', 'clutch play', 'first blood agad'
]

sections['EMERGENCY, DISTRESS & PHYSICAL THREATS'] = [
    'tulong', 'tulong po', 'saklolo', 'tulungan niyo ako', 'tulungan nyo ako',
    'tinakot ako', 'sinaktan ako', 'binugbog ako', 'sinuntok ako', 'sinipa ako',
    'hinablot gamit ko', 'ninakaw pera ko', 'magnanakaw', 'may baril', 'may kutsilyo',
    'huwag po', 'bitawan mo ako', 'bitawan mo ko', 'hawakan mo to', 'takbo',
    'tumakbo ka na', 'ibalik mo yan', 'wag mo hawakan', 'sumama ka sa amin',
    'wag ka lalapit', 'huwag kang lalapit', 'tinutukan ako', 'patayin kita',
    'papatayin kita', 'sasapakin kita', 'sasapakin ko mukha mo', 'sasakalin kita',
    'bugbugin kita', 'bugbugin ka namin', 'upakan kita', 'hampasin kita',
    'sisiguruhin kita mamaya', 'yari ka na', 'yari ka sa akin', 'huwag kang lumapit',
    'huwag kang maingay', 'wag ka maingay', 'lumayas ka dito', 'alis ka na',
    'umalis ka na dyan', 'huwag kang babalik', 'hahagupin kita', 'suntukan tayo',
    'kalaban mo ako', 'kaya mo ba ako', 'resbak kita', 'may resbak ako',
    'hahampas ako sayo', 'isasalampak kita', 'babalian kita ng buto',
    'subukan mo lang lumaban', 'ipapahiya kita sa buong school',
    'haharapin mo kami sa labas ng gate', 'itatumba kita dyan', 'titirahin kita mamaya',
    'ubos ka sa amin', 'wala kang kawala dito', 'isang salita mo pa tatamaan ka'
]

sections['INSULTS, SWEARS & SOCIAL EXCLUSION'] = [
    'pangit', 'pangit ka', 'pangit mo mukha', 'tanga', 'tanga ka', 'tanga ka talaga',
    'bobo', 'bobo ka', 'inutil', 'inutil ka', 'duwag', 'duwag ka', 'takot ka pala eh',
    'gago', 'gago ka', 'gaga ka ba', 'kupal', 'kupal ka talaga', 'bwisit', 'bwisit ka',
    'putangina', 'putangina mo', 'leche ka', 'punyeta', 'pakshet naman', 'loko ka',
    'ulol', 'ulol ka', 'gunggong', 'lintik ka', 'siraulo', 'baliw ka ba', 'engot', 'toyo ka na naman',
    'wala kang kaibigan', 'wala kang kwenta', 'walang kwenta ka', 'walang kuenta',
    'walang silbi', 'walang nagkakagusto sayo', 'walang may pake sayo', 'palamunin ka lang',
    'salot ka dito', 'mukha kang pulubi', 'ang baho mo lumayo ka', 'walang utak ka',
    'hindi ka kasali sa amin', 'layas ka dyan', 'walang may gustong makatabi ka',
    'wag kang sumabay sa amin', 'plastik mo naman', 'pabigat ka lang sa groupings',
    'puro ka asa sa amin', 'wala ka namang ambag', 'feeling magaling ka lang'
]

sections['SCHOOL, WORK & STUDENT VOCABULARY'] = [
    'klase', 'guro', 'titser', 'prinsipal', 'estudyante', 'silid aralan', 'recess',
    'baon', 'ulam', 'kanteen', 'assignment', 'project', 'exam', 'quiz', 'grupo',
    'katrabaho', 'kaklase', 'barkada', 'tropa', 'beshie', 'bestfriend', 'opisina',
    'trabaho', 'sweldo', 'sahod', 'meeting', 'boss', 'empleyado', 'pahinga', 'uwian na',
    'guidance office', 'library', 'covered court', 'faculty room', 'gate ng school',
    'cleaners ngayon', 'group presentation', 'cartolina at manila paper', 'correction tape',
    'test paper', 'chalk at eraser', 'attendance sheet', 'visitor pass', 'student id'
]

verbs_data = [
    ('gawa', 'gumawa', 'ginawa', 'gagawin', 'ginagawa', 'pinagawa', 'makagawa', 'nakagawa'),
    ('kain', 'kumain', 'kinain', 'kakain', 'kinakain', 'pakain', 'pinakain'),
    ('punta', 'pumunta', 'pinuntahan', 'pupunta', 'pupuntahan', 'papunta'),
    ('sabi', 'sinabi', 'sasabihin', 'sinasabi', 'magsasabi', 'nagsabi'),
    ('bigay', 'binigay', 'ibibigay', 'ibinibigay', 'magbigay', 'nagbigay'),
    ('kuha', 'kinuha', 'kukunin', 'kinukuha', 'kumuha', 'pakuha'),
    ('tingin', 'tumingin', 'tiningnan', 'titingnan', 'tinitingnan', 'patingin'),
    ('tulong', 'tumulong', 'tinulungan', 'tutulungan', 'tinutulungan', 'patulong'),
    ('laro', 'naglaro', 'maglalaro', 'nilalaro', 'lalaruin', 'palaro'),
    ('uwi', 'umuwi', 'inuwi', 'iuuwi', 'inuuwi', 'pauwi'),
    ('pasok', 'pumasok', 'pinasok', 'papasok', 'papasukin'),
    ('labas', 'lumabas', 'nilabas', 'ilalabas', 'inilalabas', 'palabas'),
    ('balik', 'bumalik', 'binalik', 'ibabalik', 'ibinabalik', 'pabalik'),
    ('bayad', 'nagbayad', 'magbabayad', 'binayaran', 'babayaran'),
    ('tawag', 'tumawag', 'tatawag', 'tinawagan', 'tatawagan', 'patawag'),
    ('hanap', 'naghanap', 'maghahanap', 'hinanap', 'hahanapin', 'hinahanap'),
    ('sama', 'sumama', 'sasama', 'sinamahan', 'sasamahan', 'pasama'),
    ('dating', 'dumating', 'darating', 'pinadating'),
    ('bili', 'bumili', 'bibili', 'binili', 'bibilhin', 'binibili'),
    ('benta', 'nagbenta', 'magbebenta', 'binenta', 'ibebenta', 'ibinebenta'),
    ('basa', 'bumasa', 'nagbasa', 'babasahin', 'binabasa'),
    ('sulat', 'sumulat', 'nagsulat', 'isusulat', 'isinusulat', 'isulat'),
    ('bukas', 'bumukas', 'nagbukas', 'bubuksan', 'binubuksan', 'ibukas'),
    ('sara', 'sumara', 'nagsara', 'isasara', 'isinasara', 'isara'),
    ('linis', 'luminis', 'naglinis', 'lilinisin', 'nililinis', 'palinis'),
    ('luto', 'nagluto', 'magluluto', 'niluto', 'iluluto', 'paluto'),
    ('tulog', 'natulog', 'matutulog', 'tinulugan', 'tutulugan', 'patulog'),
    ('gising', 'gumising', 'nagising', 'gigisingin', 'ginigising', 'pagising'),
    ('tayo', 'tumayo', 'tatayo', 'itinayo', 'itinatayo', 'patayo'),
    ('upo', 'umupo', 'uupo', 'inuupan', 'uupuan', 'paupo'),
    ('lakad', 'lumakad', 'lalakad', 'nilakad', 'lalakarin', 'palakad'),
    ('takbo', 'tumakbo', 'tatakbo', 'tinakbo', 'tatakbuhin', 'patakbo'),
    ('lipad', 'lumipad', 'lalipad', 'nilipad', 'liliparin'),
    ('langoy', 'lumangoy', 'lalangoy', 'nilangoy', 'lalanguyin'),
    ('kanta', 'kumanta', 'kakanta', 'kinanta', 'kakantahin'),
    ('sayaw', 'sumayaw', 'sasayaw', 'sinayaw', 'sasayawin'),
    ('iyak', 'umiyak', 'iiyak', 'iniyak', 'iiyakan', 'paiyak'),
    ('tawa', 'tumawa', 'tatawa', 'tinawanan', 'tatawanan'),
    ('ngiti', 'ngumiti', 'ngingiti', 'ningitian', 'ngingitian'),
    ('galit', 'nagalit', 'magagalit', 'kinagalitan'),
    ('sigaw', 'sumigaw', 'sasigaw', 'sinigaw', 'isisigaw'),
    ('bulong', 'bumulong', 'bubulong', 'binulong', 'ibubulong'),
    ('tago', 'tumago', 'tatago', 'tinago', 'itatago'),
    ('isip', 'umisip', 'iisip', 'inisip', 'iisipin'),
    ('hawak', 'humawak', 'hahawak', 'hinawak', 'hahawakan'),
    ('bitaw', 'bumitaw', 'bibitaw', 'binitawan', 'bibitawan'),
    ('hila', 'humila', 'hahila', 'hinila', 'hihilahin'),
    ('tulak', 'tumulak', 'tatulak', 'tinulak', 'tutulakin'),
    ('tapon', 'tumapon', 'tatapon', 'tinapon', 'itatapon'),
    ('pulot', 'pumulot', 'pupulot', 'pinulot', 'pupulutin'),
    ('ayos', 'umayos', 'aayos', 'inayos', 'aayusin'),
    ('sira', 'sumira', 'sasira', 'sinira', 'sisirain'),
    ('buhay', 'bumuhay', 'bubuhay', 'binuhay', 'buhayin'),
    ('patay', 'pumatay', 'papatay', 'pinatay', 'patayin'),
    ('tanong', 'nagtanong', 'magtatanong', 'tinanong', 'tatanungin'),
    ('sagot', 'sumagot', 'sasagot', 'sinagot', 'sasagutin')
]
sections['MASSIVE VERB CONJUGATION MATRIX'] = [item for sub in verbs_data for item in sub]

sections['COMMON NOUNS - ANATOMY & MEDICAL'] = [
    'ulo', 'buhok', 'mata', 'ilong', 'bibig', 'ngipin', 'dila', 'tainga', 'leeg',
    'balikat', 'braso', 'kamay', 'daliri', 'dibdib', 'tiyan', 'likod', 'binti',
    'tuhod', 'paa', 'dugo', 'puso', 'utak', 'buto', 'balat', 'pawis', 'luha',
    'laway', 'gamot', 'doktor', 'nars', 'ospital', 'klinika', 'sakit', 'hilo',
    'lagnat', 'ubo', 'sipon', 'sugat', 'peklat'
]

sections['COMMON NOUNS - HOUSEHOLD & OBJECTS'] = [
    'bahay', 'pinto', 'bintana', 'bubong', 'dingding', 'sahig', 'kusina', 'banyo',
    'kwarto', 'sala', 'hagdan', 'bakuran', 'mesa', 'upuan', 'kama', 'unan',
    'kumot', 'aparador', 'salamin', 'suklay', 'sabon', 'shampoo', 'tuwalya',
    'sipilyo', 'plato', 'baso', 'kutsara', 'tinidor', 'kutsilyo', 'kaldero',
    'kawali', 'sandok', 'kalan', 'gripo', 'timba', 'tabo', 'walis', 'dustpan',
    'basurahan', 'telebisyon', 'radyo', 'cellphone', 'telepono', 'laptop',
    'internet', 'wifi', 'kamera', 'relo', 'susi', 'pera', 'pitaka', 'bag',
    'payong', 'sapatos', 'tsinelas', 'damit', 'pantalon', 't-shirt', 'medyas'
]

sections['COMMON NOUNS - NATURE & ENVIRONMENT'] = [
    'araw', 'buwan', 'bituin', 'langit', 'ulap', 'ulan', 'hangin', 'bagyo',
    'kidlat', 'kulog', 'lupa', 'bundok', 'dagat', 'ilog', 'buho', 'buhangin',
    'bato', 'puno', 'halaman', 'bulaklak', 'dahon', 'ugat', 'damo', 'hayop',
    'aso', 'pusa', 'ibon', 'isda', 'manok', 'baboy', 'baka', 'kalabaw', 'kabayo',
    'kambing', 'ahas', 'daga', 'lamok', 'langaw', 'ipis', 'gagamba'
]

sections['ADJECTIVES & DESCRIPTORS'] = [
    'malaki', 'maliit', 'mahaba', 'maikli', 'mataas', 'mababa', 'malawak', 'makitid',
    'mabuti', 'masama', 'maganda', 'pangit', 'maayos', 'sira', 'bago', 'luma',
    'masaya', 'malungkot', 'galit', 'takot', 'gulat', 'inis', 'kilig', 'selos',
    'hiya', 'mabilis', 'mabagal', 'malakas', 'mahina', 'mabigat', 'magaan',
    'matigas', 'malambot', 'mainit', 'malamig', 'basa', 'tuyo', 'madilim',
    'maliwanag', 'maingay', 'tahimik', 'mahal', 'mura', 'mayaman', 'mahirap',
    'marami', 'kaunti', 'buo', 'kulang', 'matalino', 'bobo', 'masipag', 'tamad',
    'mabait', 'salbahe', 'matapang', 'duwag', 'payat', 'mataba', 'gutom',
    'busog', 'uhaw', 'antok', 'pagod', 'sariwa', 'panis', 'hinog', 'hilaw',
    'matamis', 'maasim', 'maalat', 'mapait', 'maanghang'
]

sections['FOOD, DRINKS & DINING'] = [
    'pagkain', 'kanin', 'ulam', 'tubig', 'kape', 'gatas', 'tsaa', 'juice', 'alak',
    'karneng baboy', 'karneng baka', 'manok', 'isda', 'itlog', 'gulay', 'prutas',
    'saging', 'mangga', 'mansanas', 'kaimito', 'papaya', 'bawang', 'sibuyas',
    'kamatis', 'luya', 'sili', 'asukal', 'asin', 'toyo', 'suka', 'mantika',
    'patis', 'bagoong', 'kakanin', 'tinapay', 'palaman', 'sorbetes', 'kendi', 'tsokolate'
]

sections['PRONOUNS & POINTERS'] = [
    'ako', 'ikaw', 'siya', 'tayo', 'kami', 'kayo', 'sila', 'ko', 'mo', 'niya',
    'natin', 'namin', 'ninyo', 'nila', 'akin', 'iyo', 'kanya', 'atin', 'amin',
    'inyo', 'kanila', 'ito', 'iyan', 'iyon', 'nito', 'niyan', 'noon', 'dito',
    'diyan', 'doon', 'ganito', 'ganyan', 'ganoon', 'heto', 'hayan', 'hayun',
    'nandito', 'nandiyan', 'nandoon', 'sino', 'ano', 'saan', 'kailan', 'bakit',
    'paano', 'ilan', 'gaano'
]

sections['TIME, NUMBERS & CALENDAR'] = [
    'ngayon', 'kanina', 'mamaya', 'bukas', 'kahapon', 'kaninang umaga', 'mamayang gabi',
    'maghapon', 'buong araw', 'araw-araw', 'gabi-gabi', 'linggo-linggo', 'buwan-buwan',
    'taon-taon', 'sandali', 'mamaya-maya', 'maya-maya', 'madaling araw', 'umaga',
    'tanghali', 'hapon', 'gabi', 'hatinggabi', 'lunes', 'martes', 'miyerkules',
    'huwebes', 'biyernes', 'sabado', 'linggo', 'enero', 'pebrero', 'marso',
    'abril', 'mayo', 'hunyo', 'hulyo', 'agosto', 'setyembre', 'oktubre',
    'nobyembre', 'disyembre', 'isa', 'dalawa', 'tatlo', 'apat', 'lima', 'anim',
    'pito', 'walo', 'siyam', 'sampu', 'labing-isa', 'labing-dalawa', 'dalawampu',
    'tatlumpu', 'apatnapu', 'limampu', 'isang daan', 'isang libo', 'kalahati', 'isa pa',
    'alas uno', 'alas dos', 'alas tres', 'alas kwatro', 'alas singko', 'alas seis',
    'alas siete', 'alas otso', 'alas nuebe', 'alas dies', 'alas onse', 'alas dose'
]

sections['PLACES, DIRECTIONS & TRANSPORTATION'] = [
    'lugar', 'bayan', 'siyudad', 'probinsya', 'barangay', 'kalsada', 'kalye',
    'eskinita', 'tulay', 'gusali', 'paaralan', 'tahanan', 'simbahan', 'palengke',
    'tindahan', 'mall', 'sinehan', 'parke', 'sementeryo', 'istasyon', 'sakayan',
    'babaan', 'kanan', 'kaliwa', 'deretso', 'likod', 'harap', 'taas', 'baba',
    'loob', 'labas', 'gitna', 'tabi', 'dulo', 'sasakyan', 'kotse', 'jeep',
    'bus', 'tren', 'eroplano', 'barko', 'bangka', 'bisikleta', 'motorsiklo',
    'tricycle', 'pedicab', 'pamasahe', 'bayad', 'sukli', 'preno', 'manibela', 'gulong'
]

print('Structured vocab loaded. Total base lines:', sum(len(v) for v in sections.values()))
