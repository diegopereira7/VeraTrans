from __future__ import annotations

from src.parsers.cantiza import CantizaParser
from src.parsers.agrivaldani import AgrivaldaniParser
from src.parsers.colibri import ColibriParser
from src.parsers.golden import GoldenParser
from src.parsers.latin import LatinParser
from src.parsers.mystic import MysticParser
from src.parsers.alegria import AlegriaParser
from src.parsers.sayonara import SayonaraParser
from src.parsers.life import LifeParser
from src.parsers.otros import (
    BrissasParser,
    TurflorParser,
    AlunaParser,
    DaflorParser,
    EqrParser,
    BosqueParser,
    MultifloraParser,
    FlorsaniParser,
    MaxiParser,
    PrestigeParser,
    RoselyParser,
    CondorParser,
    MalimaParser,
    MonterosaParser,
    SecoreParser,
    TessaParser,
    UmaParser,
    ValleVerdeParser,
    VerdesEstacionParser,
    FloraromaParser,
    GardaParser,
    UtopiaParser,
    ColFarmParser,
    NativeParser,
    RosaledaParser,
    UniqueParser,
    AposentosParser,
    CustomerInvoiceParser,
    PremiumColParser,
    DomenicaParser,
    InvosParser,
    MeaflosParser,
    HeraflorParser,
    InfinityParser,
    ProgresoParser,
    ColonParser,
    AguablancaParser,
    SuccessParser,
    IwaParser,
    TimanaParser,
)

from src.parsers.auto_farin import AutoParser as auto_farin_Parser

from src.parsers.auto_qualisa import AutoParser as auto_qualisa_Parser

from src.parsers.auto_agrinag import AutoParser as auto_agrinag_Parser

from src.parsers.auto_natuflor import AutoParser as auto_natuflor_Parser

from src.parsers.auto_campanario import AutoParser as auto_campanario_Parser

from src.parsers.auto_floreloy import AutoParser as auto_floreloy_Parser

from src.parsers.auto_sanjorge import AutoParser as auto_sanjorge_Parser

from src.parsers.auto_milagro import AutoParser as auto_milagro_Parser

from src.parsers.auto_mountain import AutoParser as auto_mountain_Parser

from src.parsers.auto_native import AutoParser as auto_native_Parser

from src.parsers.auto_sanfrancisco import AutoParser as auto_sanfrancisco_Parser

from src.parsers.auto_zorro import AutoParser as auto_zorro_Parser

from src.parsers.auto_cean import AutoParser as auto_cean_Parser

from src.parsers.auto_elite import AutoParser as auto_elite_Parser

FORMAT_PARSERS = {
    'auto_elite': auto_elite_Parser(),
    'auto_cean': auto_cean_Parser(),
    'auto_zorro': auto_zorro_Parser(),
    'auto_sanfrancisco': auto_sanfrancisco_Parser(),
    'auto_native': auto_native_Parser(),
    'auto_mountain': auto_mountain_Parser(),
    'auto_milagro': auto_milagro_Parser(),
    'auto_sanjorge': auto_sanjorge_Parser(),
    'auto_floreloy': auto_floreloy_Parser(),
    'auto_campanario': auto_campanario_Parser(),
    'auto_natuflor': auto_natuflor_Parser(),
    'auto_agrinag': auto_agrinag_Parser(),
    'auto_qualisa': auto_qualisa_Parser(),
    'auto_farin': auto_farin_Parser(),
    'cantiza'    : CantizaParser(),
    'agrivaldani': AgrivaldaniParser(),
    'brissas'    : BrissasParser(),
    'alegria'    : AlegriaParser(),
    'aluna'      : AlunaParser(),
    'daflor'     : DaflorParser(),
    'turflor'    : TurflorParser(),
    'eqr'        : EqrParser(),
    'bosque'     : BosqueParser(),
    'colibri'    : ColibriParser(),
    'golden'     : GoldenParser(),
    'latin'      : LatinParser(),
    'multiflora' : MultifloraParser(),
    'florsani'   : FlorsaniParser(),
    'maxi'       : MaxiParser(),
    'mystic'     : MysticParser(),
    'prestige'   : PrestigeParser(),
    'rosely'     : RoselyParser(),
    'condor'     : CondorParser(),
    'malima'     : MalimaParser(),
    'monterosa'  : MonterosaParser(),
    'secore'     : SecoreParser(),
    'tessa'      : TessaParser(),
    'uma'        : UmaParser(),
    'valleverde' : ValleVerdeParser(),
    'verdesestacion': VerdesEstacionParser(),
    'sayonara'   : SayonaraParser(),
    'life'       : LifeParser(),
    'floraroma'  : FloraromaParser(),
    'garda'      : GardaParser(),
    'utopia'     : UtopiaParser(),
    'colfarm'    : ColFarmParser(),
    'native'     : NativeParser(),
    'rosaleda'   : RosaledaParser(),
    'unique'     : UniqueParser(),
    'aposentos'  : AposentosParser(),
    'custinv'    : CustomerInvoiceParser(),
    'premiumcol' : PremiumColParser(),
    'domenica'   : DomenicaParser(),
    'invos'      : InvosParser(),
    'meaflos'    : MeaflosParser(),
    'heraflor'   : HeraflorParser(),
    'infinity'   : InfinityParser(),
    'progreso'   : ProgresoParser(),
    'colon'      : ColonParser(),
    'aguablanca' : AguablancaParser(),
    'success'    : SuccessParser(),
    'iwa'        : IwaParser(),
    'timana'     : TimanaParser(),
}
