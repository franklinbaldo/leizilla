import sys
from pathlib import Path
import dlt

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dlt_pipelines.rondonia import get_leis_rondonia

def test_rondonia_pipeline():
    # Configure the pipeline
    pipeline = dlt.pipeline(
        pipeline_name="test_rondonia_leis",
        destination="duckdb",
        dataset_name="test_leis_raw"
    )

    # Get the resource
    leis_resource = get_leis_rondonia(start_coddoc=1, end_coddoc=2)

    # Run the pipeline
    load_info = pipeline.run(leis_resource)

    # Assert that the pipeline ran successfully
    assert load_info.has_failed_jobs is False
    assert len(load_info.load_packages) == 1

    # Check the data
    with pipeline.sql_client() as client:
        with client.execute_query("SELECT * FROM leis_rondonia") as table:
            df = table.df()
            assert len(df) > 0
