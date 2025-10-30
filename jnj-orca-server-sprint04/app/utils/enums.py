from enum import Enum

# ---- Reason Enum ----
class ReasonEnum(str, Enum):
    FIRST_DRY_RUN = "First Dry Run"
    FINAL_DRY_RUN = "Final Dry Run"
    TLR = "TLR"
    CSR = "CSR"
    IA = "IA"
    AD_HOC = "Ad-hoc/Exploratory"
    PUBLICATION = "Publication"
    HAQ = "HAQ/Briefing Book"
    SET_IDMC = "SET/IDMC"
    DSUR = "DSUR/PBRER/ACO/IB"
    SCS = "SCS/ISS/SCE/ISE/SCP/CO/RMP/ADR"
    OTHER = "Other"


# ---- Role Enum ----
class RoleEnum(str, Enum):
    programmer = "programmer"
    reviewer = "reviewer"

class DocsSharedAs(str, Enum):
    PROD = "PROD"
    PREPROD = "PREPROD"