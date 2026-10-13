"""Deterministic guard controls; explicitly synthetic TZif, no package writes."""
from datetime import datetime,timezone
from io import BytesIO
import struct
from zoneinfo import ZoneInfo
import pytest
from app.domain import operator_sop_rules as rules
from app.domain.entry_storage import EntryStorageInvalid


def transition_zone():
    # Model the separately observed5h→6h gap /6h→5h fold. The installed
    # historical-time oracle was not reproducible; these guard tests do not claim
    # that this synthetic binary is approved Kyrgyzstan timezone data.
    times=[int(datetime(2004,3,27,22,tzinfo=timezone.utc).timestamp()),
           int(datetime(2004,10,30,21,tzinfo=timezone.utc).timestamp())]
    raw=b'TZif\0'+b'\0'*15+struct.pack('>6l',0,0,0,2,2,8)
    raw+=struct.pack('>2l',*times)+bytes((1,0))
    raw+=struct.pack('>lbb',18000,0,0)+struct.pack('>lbb',21600,1,4)+b'STD\0DST\0'
    return ZoneInfo.from_file(BytesIO(raw),key='Synthetic/ReviewGuard')


@pytest.mark.parametrize('on,time',[('2004-03-28','03:30'),('2004-10-31','02:30')])
def test_canonical_guard_rejects_actual_gap_or_fold_in_pinned_zone(on,time,monkeypatch):
    zone=transition_zone();wall=datetime.fromisoformat(on+'T'+time)
    assert wall.replace(tzinfo=zone,fold=0).utcoffset()!=wall.replace(tzinfo=zone,fold=1).utcoffset()
    monkeypatch.setattr(rules,'BISHKEK',zone)
    with pytest.raises(EntryStorageInvalid,match='operator_sop_time_ambiguous_or_missing'):
        rules.selected_schedule(dict(on=on,time=time,reason='verify_missing_facts',reference='SYNTHETIC',proof='a'*64))
