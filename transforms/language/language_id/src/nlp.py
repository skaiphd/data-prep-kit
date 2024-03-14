import os


os.environ["OPENBLAS_NUM_THREADS"] = "1"

from typing import Any

import pandas as pd
import pyarrow as pa
from data_processing.utils import TransformUtils, get_logger
from lang_models import LangModel


logger = get_logger(__name__)


def get_lang_ds_pa(table: pa.table, nlp: LangModel, col_name: str = "contents") -> tuple[pa.table, dict[str, Any]]:
    try:
        detected_language = pa.table(
            pd.DataFrame(map(lambda x: nlp.detect_lang(x), table[col_name].to_pylist()), columns=["lang", "score"])
        )
    except Exception as e:
        logger.warning("ERROR: %s, kipping the file", e)
        return None, None
    stats = pa.table([detected_language["lang"]], names=["lang"]).group_by("lang").aggregate([("lang", "count")])
    stats_dict = {}
    for batch in stats.to_batches():
        d = batch.to_pydict()
        for lang, count in zip(d["lang"], d["lang_count"]):
            stats_dict[lang] = count
    result = pa.table([detected_language["lang"]], names=["ft_lang"])
    result = TransformUtils.add_column(table=result, name="ft_score", content=detected_language["score"])
    return result, stats_dict
