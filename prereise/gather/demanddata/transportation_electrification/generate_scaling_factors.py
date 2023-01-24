import warnings

import pandas as pd
from powersimdata.network.constants.region.geography import USA

warnings.simplefilter(action="ignore", category=UserWarning)

census_ua_url = "https://www2.census.gov/geo/docs/reference/ua/ua_st_list_all.xls"
census_state_url = "https://www2.census.gov/programs-surveys/popest/tables/2010-2019/state/totals/nst-est2019-01.xlsx"
tht_data_url = "https://www7.transportation.gov/file/51021/download?token=2nJBkBSM"

state2abv = USA().state2abv | {"District of Columbia": "DC"}
id2state = {
    "01": "AL",
    "02": "AK",
    "04": "AZ",
    "05": "AR",
    "06": "CA",
    "08": "CO",
    "09": "CT",
    "10": "DE",
    "11": "DC",
    "12": "FL",
    "13": "GA",
    "15": "HI",
    "16": "ID",
    "17": "IL",
    "18": "IN",
    "19": "IA",
    "20": "KS",
    "21": "KY",
    "22": "LA",
    "23": "ME",
    "24": "MD",
    "25": "MA",
    "26": "MI",
    "27": "MN",
    "28": "MS",
    "29": "MO",
    "30": "MT",
    "31": "NE",
    "32": "NV",
    "33": "NH",
    "34": "NJ",
    "35": "NM",
    "36": "NY",
    "37": "NC",
    "38": "ND",
    "39": "OH",
    "40": "OK",
    "41": "OR",
    "42": "PA",
    "44": "RI",
    "45": "SC",
    "46": "SD",
    "47": "TN",
    "48": "TX",
    "49": "UT",
    "50": "VT",
    "51": "VA",
    "53": "WA",
    "54": "WV",
    "55": "WI",
    "56": "WY",
}


def load_census_ua(path):
    """Load census data for urban population

    :param str path: path to census file (local or url)
    :return: (*dict*) -- keys are state abbreviation and values are data frames giving
        population by urban area in the state.
    """
    df = pd.read_excel(
        path,
        index_col=0,
        keep_default_na=False,
        usecols=[1, 2, 4],
        skiprows=2,
    )
    state2ua = {}
    for n, s in id2state.items():
        state2ua[s] = df.query("STATE==@n")["POP"]

    return state2ua


def load_census_state(path, year=None):
    """Load census data for state population

    :param str path: path to census file (local or url)
    :param str year: year to query for state population.
    :return: (*pandas.Series*) -- indices are state abbreviations and values are
        population in state
    """
    if year is None:
        year = 2015

    df = pd.read_excel(path, skiprows=3, index_col=0, skipfooter=7)
    df.index = df.index.map(lambda x: str(x)[1:])

    return df.loc[state2abv.keys()][year].rename(index=state2abv)


def load_dot_vmt_per_capita(path):
    """Load Vehicle Miles Traveled (VMT) per capita in urban areas

    :param str path: path to Department of Transportation's Transportation Health Tools
        (local or url)
    :return: (*tuple*) -- series. Indices are state abbreviations and values are
        VMT per capita in urban area (first element) or state (second element)
    """
    df_ua = pd.read_excel(
        path,
        sheet_name="Urbanized Area",
        index_col=0,
        usecols=[0, 3],
        names=["UA", "VMT per Capita (daily)"],
    )

    df_state = pd.read_excel(
        path,
        sheet_name="State",
        index_col=0,
        usecols=[0, 39],
        names=["State", "VMT per Capita (annual)"],
    )

    return (
        df_ua.squeeze().loc[lambda x: x != "[no data]"],
        df_state.rename(index=state2abv).squeeze(),
    )


def calculate_vmt_for_ua(census_ua, tht_ua):
    """Calculate the total annual Vehicle Miles Traveled (VMT) in urban areas

    :param dict census_ua: dictionary as returned by :func:`load_census_ua`
    :param pandas.Series tht_ua: vmt per capita in urban areas as returned by
        :func:`load_dot_vmt_per_capita`
    :return: (*dict*) -- keys are state abbreviations and values are series giving
        annual vmt by urban areas.
    """

    tht_ua_format = tht_ua.copy()
    vmt_for_ua = {}

    tht_ua_format.index = tht_ua_format.index.str.replace(r"[, -.]", "", regex=True)
    format2original = dict(zip(tht_ua_format.index, tht_ua.index))

    for s in census_ua:
        census_ua_format = census_ua[s].copy()
        census_ua_format.index = census_ua_format.index.str.replace(
            r"[, -.]", "", regex=True
        )
        common = set(tht_ua_format.index).intersection(set(census_ua_format.index))
        vmt_for_ua[s] = (
            pd.DataFrame(
                {
                    "Annual VMT": [
                        365 * tht_ua_format.loc[i] * census_ua_format.loc[i]
                        for i in common
                    ]
                },
                index=list(common),
            )
            .rename(index=format2original)
            .squeeze()
        )

    return vmt_for_ua


def calculate_vmt_for_state(census_state, tht_state):
    """Calculate the total annual Vehicle Miles Traveled (VMT) in states

    :param dict census_state: dictionary as returned by :func:`load_census_state`
    :param pandas.Series tht_state: vmt per capita in states as returned by
        :func:`load_dot_vmt_per_capita`
    :return: (*pandas.Series*) -- indices are state abbreviations and values are annual
        VMT in state.
    """
    common = list(set(tht_state.index).intersection(set(census_state.index)))
    vmt_for_state = tht_state.loc[common] * census_state.loc[common]

    return vmt_for_state


def calculate_urban_rural_fraction(vmt_for_ua, vmt_for_state):
    """Calculate the percentage of Vehicle Miles Traveled (VMT) in urban and rural areas

    :param dict vmt_for_ua: dictionary as returned by :func:`calculate_vmt_for_ua`.
    :param pandas.Series vmt_for_state: series as returned by
        :func:`calculate_vmt_for_state`
    :return: (*tuple*) -- keys are state abbreviations and values are either series of
        percentage vmt in urban areas (first element) or percentage in rural area
        (second element)
    """
    vmt_for_ua_perc = vmt_for_ua.copy()
    vmt_for_ra_perc = {}
    for s in vmt_for_ua:
        if s in vmt_for_state.index:
            vmt_for_ua_perc[s] = vmt_for_ua[s] / vmt_for_state.loc[s]
            vmt_for_ra_perc[s] = 1 - vmt_for_ua_perc[s].sum()
        # Handle District of Columbia
        else:
            vmt_for_ua_perc[s] = 1
            vmt_for_ra_perc[s] = 0

    return vmt_for_ua_perc, vmt_for_ra_perc
