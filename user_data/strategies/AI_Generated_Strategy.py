from freqtrade.strategy.interface import IStrategy
from pandas import DataFrame
import talib.abstract as ta
from freqtrade.strategy import merge_informative_pair


class AI_Generated_Strategy(IStrategy):
    INTERFACE_VERSION = 3

    can_short = False
    timeframe = "5m"
    informative_timeframe = "1h"

    startup_candle_count = 220

    minimal_roi = {
        "0": 0.04,
        "60": 0.02,
        "180": 0.01,
        "360": 0.0,
    }

    stoploss = -0.08
    trailing_stop = False

    process_only_new_candles = True
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False

    position_adjustment_enable = False

    def informative_pairs(self):
        pairs = self.dp.current_whitelist()
        return [(pair, self.informative_timeframe) for pair in pairs]

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ema20"] = ta.EMA(dataframe, timeperiod=20)
        dataframe["ema50"] = ta.EMA(dataframe, timeperiod=50)
        dataframe["ema200"] = ta.EMA(dataframe, timeperiod=200)
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["adx"] = ta.ADX(dataframe, timeperiod=14)

        macd = ta.MACD(dataframe)
        dataframe["macd"] = macd["macd"]
        dataframe["macdsignal"] = macd["macdsignal"]

        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["atr_pct"] = dataframe["atr"] / dataframe["close"]

        inf_tf = self.dp.get_pair_dataframe(pair=metadata["pair"], timeframe=self.informative_timeframe)
        inf_tf["ema200"] = ta.EMA(inf_tf, timeperiod=200)
        inf_tf["rsi"] = ta.RSI(inf_tf, timeperiod=14)

        dataframe = merge_informative_pair(
            dataframe,
            inf_tf[["date", "close", "ema200", "rsi"]],
            self.timeframe,
            self.informative_timeframe,
            ffill=True,
        )

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                (dataframe["volume"] > 0)
                & (dataframe["close"] > dataframe["ema20"])
                & (dataframe["rsi"] > 35)
                & (dataframe["rsi"] < 72)
                & (dataframe["macd"] > dataframe["macdsignal"])
                & (dataframe["adx"] > 10)
                & (dataframe["atr_pct"] > 0.001)
                & (dataframe["atr_pct"] < 0.06)
                & (
                    (dataframe["close_1h"] > dataframe["ema200_1h"])
                    | (dataframe["rsi_1h"] > 45)
                )
            ),
            ["enter_long", "enter_tag"],
        ] = (1, "relaxed_entry")

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                (dataframe["volume"] > 0)
                & (dataframe["close"] < dataframe["ema50"])
                & (dataframe["rsi"] < 40)
                & (dataframe["macd"] < dataframe["macdsignal"])
            ),
            ["exit_long", "exit_tag"],
        ] = (1, "soft_exit")

        return dataframe
