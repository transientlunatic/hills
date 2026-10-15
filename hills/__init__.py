import click
import pandas as pd

import warnings
warnings.filterwarnings("ignore")

@click.command()
@click.argument("hill")
@click.option("--full", "full", is_flag=True, default=False)
def hello(hill, full):
    """Find a hill in the DoBIH"""
    data = pd.read_csv("../data/DoBIH_v18_4.csv", index_col="Number")

    click.echo(data.columns)
    
    if not full:
        subset = data[["Name", "Feature", "Metres", "Classification"]]
    else:
        subset = data

    result = subset.query(f"""Name.str.contains("{hill}")""")
    click.echo(result)

if __name__ == '__main__':
    hello()
