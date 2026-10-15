"""
Data types for the hills package.
"""
from dataclasses import dataclass

@dataclass
class HillClassification:
    """
    The hill classification object represents a single classification type.

    Attributes
    ----------
    code : str
        The code for the classification (e.g., 'Ma' for Marilyn).
    name : str
        The full name of the classification.
    """
    code: str
    name: str

classifications = {
    "Ma": HillClassification("Ma", "Marilyn"),
    "Hu": HillClassification("Hu", "Hump"),
    "Sim": HillClassification("Sim", "Simm"),
    "5": HillClassification("5", "Dodd"),
    "M": HillClassification("M", "Munro"),
    "MT": HillClassification("MT", "Munro Top"),
    "F": HillClassification("F", "Furth"),
    "C": HillClassification("C", "Corbett"),
    "G": HillClassification("G", "Graham"),
    "D": HillClassification("D", "Donald"),
    "DT": HillClassification("DT", "Donald Top"),
    "Hew": HillClassification("Hew", "Hewitt"),
    "N": HillClassification("N", "Nuttall"),
    "Dew": HillClassification("Dew", "Dewey"),
    "DDew": HillClassification("DDew", "Donald Dewey"),
    "HF": HillClassification("HF", "Highland Five"),
    "4": HillClassification("4", "400-499m Tump"),
    "3": HillClassification("3", "300-399m Tump (GB)"),
    "2": HillClassification("2", "200-299m Tump (GB)"),
    "1": HillClassification("1", "100-199m Tump (GB)"),
    "0": HillClassification("0", "0-99m Tump (GB)"),
    "W": HillClassification("W", "Wainwright"),
    "WO": HillClassification("WO", "Wainwright Outlying Fell"),
    "B": HillClassification("B", "Birkett"),
    "Sy": HillClassification("Sy", "Synge"),
    "Fel": HillClassification("Fel", "Fellranger"),
    "E": HillClassification("E", "Ethel"),
    "HHB": HillClassification("HHB", "High Hill of Britain"),
    "CoH": HillClassification("CoH", "County Top – Historic (pre-1974)"),
    "CoA": HillClassification("CoA", "County Top – Administrative (1974 to mid-1990s)"),
    "CoU": HillClassification("CoU", "County Top – Current County or Unitary Authority"),
    "CoL": HillClassification("CoL", "County Top – Current London Borough"),
    "SIB": HillClassification("SIB", "Significant Island of Britain"),
    "Dil": HillClassification("Dil", "Dillon"),
    "A": HillClassification("A", "Arderin"),
    "VL": HillClassification("VL", "Vandeleur-Lynam"),
    "O": HillClassification("O", "Other list"),
    "Un": HillClassification("Un", "unclassified"),
    "xMT": HillClassification("xMT", "deleted Munro Top"),
    "xC": HillClassification("xC", "deleted Corbett"),
    "xG": HillClassification("xG", "deleted Graham"),
    "xN": HillClassification("xN", "deleted Nuttall"),
    "xDT": HillClassification("xDT", "deleted Donald Top"),
    }

class Hill:
    """
    The hill object represents a single hill with its attributes.

    Notes
    -----
    There are a number of types of hill in the British Isles, each with their own
    classification criteria. These are represented as boolean attributes in the database 
    which are mapped to a list of classifications in the object.

    Ma – Marilyn 
    Hu – Hump
    Sim – Simm 
    5 – Dodd 
    M – Munro 
    MT – Munro Top 
    F – Furth 
    C – Corbett 
    G – Graham 
    D – Donald 
    DT – Donald Top 
    Hew – Hewitt 
    N – Nuttall 
    Dew – Dewey 
    DDew – Donald Dewey 
    HF – Highland Five 
    4 – 400-499m Tump 
    3 – 300-399m Tump (GB) 
    2 – 200-299m Tump (GB) 
    1 – 100-199m Tump (GB) 
    0 – 0-99m Tump (GB) 	W – Wainwright
    WO – Wainwright Outlying Fell
    B – Birkett
    Sy – Synge
    Fel – Fellranger
    E – Ethel
    HHB – High Hill of Britain
    CoH – County Top – Historic (pre-1974)
    CoA – County Top – Administrative (1974 to mid-1990s)
    CoU – County Top – Current County or Unitary Authority
    CoL – County Top – Current London Borough
    SIB – Significant Island of Britain
    Dil – Dillon
    A – Arderin
    VL – Vandeleur-Lynam
    O – Other list
    Un – unclassified
    Prefixes
    s – sub
    x – deleted
    Suffixes
    = twin
    """
    def __init__(self, **kwargs: dict):
        self.name: str = kwargs["Name"]
        self.height_m: float = kwargs["Metres"]
        self.col_height_m: float = kwargs["Col height"]
        self.grid_ref: str = kwargs["Grid ref"]
        self.latitude: float = kwargs["Latitude"]
        self.longitude: float = kwargs["Longitude"]
        self.classifications: list[HillClassification] = []

        for code, classification in classifications.items():
            if kwargs.get(code) == 1:
                self.classifications.append(classification)

    def _from_pandas_row(row) -> "Hill":
        """
        Create a Hill object from a pandas DataFrame row.

        Parameters
        ----------
        row : pandas.Series
            A row from a pandas DataFrame representing a hill.

        Returns
        -------
        Hill
            The Hill object created from the DataFrame row.
        """
        return Hill(**row.to_dict())
    
    

