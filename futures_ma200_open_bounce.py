# futures_ma200_open_bounce.py  (auto-saved by push_to_github)

def install(pkg):
    subprocess.check_call([sys.executable, "-m", "pip", "install", pkg, "-q"])



def fetch_chunked(ticker: str) -> pd.DataFrame:
    end   = datetime.now()
    start = end - timedelta(days=YEARS_BACK * 365)
    chunks, chunk_end = [], end

    print(f"\n[data] Fetching {INTERVAL} data for {ticker} ({TICKERS[ticker]}) ...")
    while chunk_end > start:
        chunk_start = max(chunk_end - timedelta(days=CHUNK_DAYS), start)
        try:
            df = yf.download(
                tickers=ticker,
                start=chunk_start.strftime("%Y-%m-%d"),
                end=chunk_end.strftime("%Y-%m-%d"),
                interval=INTERVAL,
                auto_adjust=True,
                progress=False,
            )
            if not df.empty:
                chunks.append(df)
        except Exception as e:
            print(f"  [warn] {chunk_start.date()}→{chunk_end.date()} failed: {e}")
        chunk_end = chunk_start

    if not chunks:
        raise RuntimeError(f"No data returned for {ticker}.")

    out = pd.concat(chunks).sort_index()
    out = out[~out.index.duplicated(keep="last")]

    if isinstance(out.columns, pd.MultiIndex):
        out.columns = [col[0].lower() for col in out.columns]
    else:
        out.columns = [c.lower() for c in out.columns]

    if out.index.tz is None:
        out.index = out.index.tz_localize("UTC")
    out.index = out.index.tz_convert(ET)

    print(f"  {len(out):,} candles  |  {out.index[0].date()} -> {out.index[-1].date()}")
    return out



def add_ma(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["ma200"]        = df["close"].rolling(MA_PERIOD).mean()
    df["pct_below_ma"] = (df["ma200"] - df["close"]) / df["ma200"] * 100
    return df.dropna(subset=["ma200"])



def build_open_records(df: pd.DataFrame) -> pd.DataFrame:
    records = []
    dates   = sorted(set(df.index.date))

    for d in dates:
        day_df = df[df.index.date == d]

        open_candles = day_df[
            (day_df.index.hour == OPEN_HOUR_ET) &
            (day_df.index.minute == OPEN_MIN_ET)
        ]
        if open_candles.empty:
            continue

        open_row   = open_candles.iloc[0]
        open_time  = open_candles.index[0]
        open_price = open_row["close"]
        deviation  = open_row["pct_below_ma"]
        ma_val     = open_row["ma200"]

        window_end = open_time + timedelta(minutes=SESSION_END_MIN)
        window_df  = day_df[
            (day_df.index >= open_time) &
            (day_df.index <= window_end)
        ]
        if window_df.empty:
            continue

        up_target  = open_price + TICK_TARGET
        sl_level   = open_price - STOP_LOSS

        bounce_50  = False
        sl_hit     = False
        outcome    = "open"   # neither hit within session
        exit_time  = None
        exit_price = None
        max_up_pts = 0.0
        max_dn_pts = 0.0

        for t, candle in window_df.iterrows():
            up_move = candle["high"]  - open_price
            dn_move = open_price      - candle["low"]
            max_up_pts = max(max_up_pts, up_move)
            max_dn_pts = max(max_dn_pts, dn_move)

            if not bounce_50 and not sl_hit:
                if candle["high"] >= up_target:
                    bounce_50  = True
                    outcome    = "win"
                    exit_time  = t
                    exit_price = up_target
                    break
                if candle["low"] <= sl_level:
                    sl_hit     = True
                    outcome    = "loss"
                    exit_time  = t
                    exit_price = sl_level
                    break

        records.append({
            "date":         d,
            "open_time":    open_time,
            "open_price":   round(open_price, 2),
            "ma200":        round(ma_val, 2),
            "deviation":    round(deviation, 4),
            "up_target":    round(up_target, 2),
            "sl_level":     round(sl_level, 2),
            "bounce_50":    bounce_50,
            "sl_hit":       sl_hit,
            "outcome":      outcome,
            "exit_time":    exit_time,
            "exit_price":   round(exit_price, 2) if exit_price else None,
            "max_up_pts":   round(max_up_pts, 2),
            "max_dn_pts":   round(max_dn_pts, 2),
            "session_high": round(window_df["high"].max(), 2),
            "session_low":  round(window_df["low"].min(), 2),
        })

    return pd.DataFrame(records)



def analyse_buckets(records: pd.DataFrame) -> pd.DataFrame:
    below = records[records["deviation"] > 0].copy()
    edges = np.arange(0, MAX_DEV + BUCKET_SIZE, BUCKET_SIZE)
    rows  = []

    for lo in edges[:-1]:
        hi     = lo + BUCKET_SIZE
        subset = below[(below["deviation"] >= lo) & (below["deviation"] < hi)]
        n      = len(subset)
        if n < 1:
            continue
        wins   = subset["bounce_50"].sum()
        losses = subset["sl_hit"].sum()
        rows.append({
            "deviation_bucket": f"{lo:.2f}% - {hi:.2f}%",
            "lo":               lo,
            "hi":               hi,
            "n_days":           n,
            "wins":             int(wins),
            "losses":           int(losses),
            "win_rate_%":       round(wins / n * 100, 1),
            "avg_max_up_pts":   round(subset["max_up_pts"].mean(), 1),
            "avg_max_dn_pts":   round(subset["max_dn_pts"].mean(), 1),
        })

    return pd.DataFrame(rows)



def find_optimal_bucket(buckets: pd.DataFrame) -> pd.Series:
    eligible = buckets[buckets["n_days"] >= MIN_SAMPLES]
    if eligible.empty:
        eligible = buckets
    return eligible.loc[eligible["win_rate_%"].idxmax()]



def plot_trade_overview(df: pd.DataFrame, records: list, ticker: str):
    if not records:
        return

    fig, ax = plt.subplots(figsize=(22, 9))
    fig.patch.set_facecolor("#0d1117")
    ax.set_facecolor("#0d1117")

    BG     = "#0d1117"
    BLUE   = "#4a9eff"
    GREEN  = "#2ecc71"
    RED    = "#e74c3c"
    ORANGE = "#e87040"
    WHITE  = "#ffffff"
    GREY   = "#888888"

    all_times, all_closes = [], []
    entry_times,  entry_prices  = [], []
    win_times,    win_prices    = [], []
    loss_times,   loss_prices   = [], []

    for rec in records:
        day_df = df[df.index.date == rec["date"]]
        day_df = day_df[
            (day_df.index.hour >= 9) &
            ((day_df.index.hour < 11) | ((day_df.index.hour == 11) & (day_df.index.minute == 0)))
        ]
        if day_df.empty:
            continue

        all_times.extend(day_df.index.tolist())
        all_closes.extend(day_df["close"].tolist())

        entry_times.append(rec["open_time"])
        entry_prices.append(rec["open_price"])

        if rec["outcome"] == "win" and rec["exit_time"] is not None:
            win_times.append(rec["exit_time"])
            win_prices.append(rec["up_target"])
        elif rec["outcome"] == "loss" and rec["exit_time"] is not None:
            loss_times.append(rec["exit_time"])
            loss_prices.append(rec["sl_level"])

    if not all_times:
        plt.close(fig)
        return

    # Price line
    ax.plot(all_times, all_closes, color=BLUE, lw=0.9, alpha=0.65, zorder=2)

    # Entry markers (blue triangle up)
    ax.scatter(entry_times, entry_prices, marker="^", s=130,
               color="#00bfff", zorder=5, edgecolors=WHITE, linewidths=0.5,
               label=f"Entry (open below 200 MA)")

    # TP hit (green star)
    if win_times:
        ax.scatter(win_times, win_prices, marker="*", s=180,
                   color=GREEN, zorder=6, edgecolors=WHITE, linewidths=0.4,
                   label=f"+{TICK_TARGET}pt target hit ✓")

    # SL hit (red X)
    if loss_times:
        ax.scatter(loss_times, loss_prices, marker="X", s=130,
                   color=RED, zorder=6, edgecolors=WHITE, linewidths=0.4,
                   label=f"−{STOP_LOSS}pt SL hit ✗")

    # Date labels on entry markers (every marker)
    for t, p in zip(entry_times, entry_prices):
        ax.annotate(
            t.strftime("%b %d"),
            xy=(t, p), xytext=(0, -14),
            textcoords="offset points",
            ha="center", va="top",
            fontsize=6.5, color=GREY,
            clip_on=True,
        )

    # X-axis formatting
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d\n%H:%M"))
    ax.xaxis.set_major_locator(mdates.HourLocator(interval=1))
    plt.setp(ax.get_xticklabels(), color=WHITE, fontsize=7)
    plt.setp(ax.get_yticklabels(), color=WHITE, fontsize=8)

    wins   = sum(1 for r in records if r["outcome"] == "win")
    losses = sum(1 for r in records if r["outcome"] == "loss")
    total  = len(records)
    rr     = TICK_TARGET / STOP_LOSS

    ax.set_xlabel("Date / Time (ET)", color=GREY, fontsize=10)
    ax.set_ylabel("Price (pts)", color=GREY, fontsize=10)
    ax.grid(alpha=0.12, color=WHITE, linestyle=":", lw=0.6)
    ax.set_title(
        f"{ticker} — {TICKERS[ticker]}  |  200 MA Open-Deviation Bounce Strategy\n"
        f"TP: +{TICK_TARGET}pts  |  SL: −{STOP_LOSS}pts  |  R:R = 1:{rr:.1f}  |  "
        f"Signal days: {total}  |  Wins: {wins}  Losses: {losses}  |  "
        f"Win rate: {wins/total*100:.0f}%",
        color=WHITE, fontsize=11, pad=12
    )
    ax.legend(loc="upper left", facecolor="#1a1a2e", labelcolor=WHITE,
              edgecolor="#444", fontsize=9)
    ax.spines[:].set_color("#333")
    plt.tight_layout()

    fname = f"{ticker.replace('=','')}_trade_overview.png"
    plt.savefig(fname, dpi=150, bbox_inches="tight", facecolor=BG)
    print(f"  [chart] Trade overview saved -> {fname}")
    plt.close(fig)



def plot_single_day(df: pd.DataFrame, rec: dict, ticker: str, suffix: str = ""):
    day_df = df[df.index.date == rec["date"]].copy()
    day_df = day_df[
        (day_df.index.hour >= 9) &
        ((day_df.index.hour < 11) | ((day_df.index.hour == 11) & (day_df.index.minute == 0)))
    ]
    if day_df.empty:
        return

    BG    = "#0d1117"
    GREEN = "#2ecc71"
    RED   = "#e74c3c"
    BLUE  = "#00bfff"
    WHITE = "#ffffff"
    GREY  = "#888888"

    fig, ax = plt.subplots(figsize=(17, 7))
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)

    times = list(day_df.index)
    xs    = np.arange(len(times))

    for i, (t, row) in enumerate(day_df.iterrows()):
        col = GREEN if row["close"] >= row["open"] else RED
        ax.plot([i, i], [row["low"], row["high"]], color=col, lw=1.3, zorder=2)
        body_bot = min(row["open"], row["close"])
        body_top = max(row["open"], row["close"])
        ax.add_patch(plt.Rectangle(
            (i - 0.3, body_bot), 0.6, max(body_top - body_bot, 0.5),
            color=col, zorder=3
        ))

    # Horizontal level lines
    ax.axhline(rec["open_price"], color=BLUE,  lw=1.8, linestyle="--", alpha=0.9, zorder=4,
               label=f"Entry  {rec['open_price']:.0f}")
    ax.axhline(rec["up_target"], color=GREEN, lw=1.8, linestyle="--", alpha=0.9, zorder=4,
               label=f"TP +{TICK_TARGET}pts  {rec['up_target']:.0f}")
    ax.axhline(rec["sl_level"],  color=RED,   lw=1.8, linestyle="--", alpha=0.9, zorder=4,
               label=f"SL −{STOP_LOSS}pts  {rec['sl_level']:.0f}")

    # Right-side price labels
    xlim_right = len(times) - 0.5
    for level, col, lbl in [
        (rec["open_price"], BLUE,  f"ENTRY\n{rec['open_price']:.0f}"),
        (rec["up_target"],  GREEN, f"TP\n{rec['up_target']:.0f}"),
        (rec["sl_level"],   RED,   f"SL\n{rec['sl_level']:.0f}"),
    ]:
        ax.annotate(lbl, xy=(xlim_right, level), xytext=(4, 0),
                    textcoords="offset points", va="center",
                    color=col, fontsize=8, fontweight="bold", clip_on=False)

    # Shaded zones
    ax.axhspan(rec["open_price"], rec["up_target"], alpha=0.07, color=GREEN, zorder=1)
    ax.axhspan(rec["sl_level"],   rec["open_price"], alpha=0.07, color=RED,   zorder=1)

    # Entry marker
    ax.scatter([0], [rec["open_price"] - (rec["open_price"] * 0.0008)],
               marker="^", s=220, color=BLUE, zorder=7,
               edgecolors=WHITE, linewidths=0.8)
    ax.annotate(f"ENTRY\n{times[0].strftime('%H:%M')}", xy=(0, rec["open_price"]),
                xytext=(0.4, rec["open_price"] - (rec["open_price"] * 0.002)),
                color=BLUE, fontsize=8)

    # Exit marker + annotation
    outcome_label = "— session closed —"
    if rec["outcome"] == "win" and rec["exit_time"] is not None:
        try:
            ei = times.index(rec["exit_time"])
            ax.scatter([ei], [rec["up_target"]], marker="*", s=320,
                       color=GREEN, zorder=8, edgecolors=WHITE, linewidths=0.5)
            ax.annotate(f"✓ TARGET HIT\n{rec['exit_time'].strftime('%H:%M')}",
                        xy=(ei, rec["up_target"]),
                        xytext=(ei + 0.3, rec["up_target"] + rec["open_price"] * 0.001),
                        color=GREEN, fontsize=8.5, fontweight="bold")
            outcome_label = f"✓ TARGET HIT  +{TICK_TARGET}pts"
        except ValueError:
            pass
    elif rec["outcome"] == "loss" and rec["exit_time"] is not None:
        try:
            ei = times.index(rec["exit_time"])
            ax.scatter([ei], [rec["sl_level"]], marker="X", s=220,
                       color=RED, zorder=8, edgecolors=WHITE, linewidths=0.5)
            ax.annotate(f"✗ STOPPED OUT\n{rec['exit_time'].strftime('%H:%M')}",
                        xy=(ei, rec["sl_level"]),
                        xytext=(ei + 0.3, rec["sl_level"] - rec["open_price"] * 0.001),
                        color=RED, fontsize=8.5, fontweight="bold")
            outcome_label = f"✗ STOPPED OUT  −{STOP_LOSS}pts"
        except ValueError:
            pass

    # X-axis: show time label for every candle
    ax.set_xticks(xs)
    ax.set_xticklabels(
        [t.strftime("%H:%M") for t in times],
        color=WHITE, fontsize=8, rotation=45, ha="right"
    )
    plt.setp(ax.get_yticklabels(), color=WHITE, fontsize=9)

    rr = TICK_TARGET / STOP_LOSS
    ax.set_xlabel(f"Time ET — {rec['date'].strftime('%A %d %B %Y')}", color=GREY, fontsize=10)
    ax.set_ylabel("Price (pts)", color=GREY, fontsize=10)
    ax.grid(alpha=0.1, color=WHITE, linestyle=":", lw=0.6)
    ax.set_title(
        f"{ticker} — {rec['date']}  |  Dev: {rec['deviation']:.2f}% below 200 MA  |  "
        f"R:R = 1:{rr:.1f}  |  {outcome_label}",
        color=WHITE, fontsize=11, pad=10
    )
    ax.legend(loc="upper right", facecolor="#1a1a2e", labelcolor=WHITE,
              edgecolor="#444", fontsize=9)
    ax.spines[:].set_color("#333")
    ax.set_xlim(-0.7, len(times) + 1.5)

    plt.tight_layout()
    fname = f"{ticker.replace('=','')}_single_day_detail{suffix}.png"
    plt.savefig(fname, dpi=150, bbox_inches="tight", facecolor=BG)
    print(f"  [chart] Single-day detail saved -> {fname}")
    plt.close(fig)



def plot_win_rate_chart(buckets: pd.DataFrame, optimal: pd.Series, ticker: str):
    BG    = "#0d1117"
    GREEN = "#2ecc71"
    BLUE  = "#3d8bcd"
    ORA   = "#e87040"
    WHITE = "#ffffff"
    GREY  = "#888888"

    fig, ax1 = plt.subplots(figsize=(14, 6))
    fig.patch.set_facecolor(BG)
    ax1.set_facecolor(BG)

    x      = np.arange(len(buckets))
    colors = [GREEN if row["lo"] == optimal["lo"] else BLUE
              for _, row in buckets.iterrows()]

    ax1.bar(x, buckets["win_rate_%"], width=0.6, color=colors, alpha=0.85, zorder=3)
    ax1.set_xticks(x)
    ax1.set_xticklabels(buckets["deviation_bucket"], rotation=45,
                        ha="right", fontsize=8, color=WHITE)
    ax1.set_ylabel(f"Win Rate % (TP +{TICK_TARGET}pts / SL −{STOP_LOSS}pts)",
                   color=WHITE, fontsize=10)
    ax1.tick_params(colors=WHITE)
    ax1.set_xlabel("% Deviation Below 200 MA at 9:30 ET Open", color=GREY, fontsize=10)
    ax1.grid(axis="y", alpha=0.2, color=WHITE)
    ax1.set_ylim(0, min(105, buckets["win_rate_%"].max() + 15))

    ax2 = ax1.twinx()
    ax2.plot(x, buckets["n_days"], color=ORA, lw=2, marker="o", ms=5)
    ax2.set_ylabel("Sample Days (n)", color=ORA, fontsize=10)
    ax2.tick_params(colors=ORA)
    ax2.set_facecolor(BG)

    opt_rows = buckets[buckets["lo"] == optimal["lo"]]
    if not opt_rows.empty:
        i = list(buckets.index).index(opt_rows.index[0])
        ax1.annotate(
            f"BEST\n{optimal['win_rate_%']:.0f}%",
            xy=(i, optimal["win_rate_%"]),
            xytext=(min(i + 1, len(buckets) - 1), optimal["win_rate_%"] + 5),
            color=GREEN, fontsize=9, fontweight="bold",
            arrowprops=dict(arrowstyle="->", color=GREEN),
        )

    rr = TICK_TARGET / STOP_LOSS
    ax1.legend(
        handles=[
            mpatches.Patch(color=GREEN, label="Best bucket"),
            mpatches.Patch(color=BLUE,  label="Other buckets"),
            plt.Line2D([0],[0], color=ORA, marker="o", label="Sample days"),
        ],
        loc="upper right", facecolor="#1a1a2e", labelcolor=WHITE, edgecolor="#444"
    )
    ax1.set_title(
        f"{ticker} — {TICKERS[ticker]}\n"
        f"Win Rate by Opening Deviation from 200 MA  |  "
        f"TP: +{TICK_TARGET}pts  |  SL: −{STOP_LOSS}pts  |  R:R 1:{rr:.1f}",
        color=WHITE, fontsize=11
    )
    ax1.spines[:].set_color("#333")
    ax2.spines[:].set_color("#333")
    plt.tight_layout()

    fname = f"{ticker.replace('=','')}_win_rate_by_deviation.png"
    plt.savefig(fname, dpi=150, bbox_inches="tight", facecolor=BG)
    print(f"  [chart] Win-rate chart saved -> {fname}")
    plt.close(fig)



def plot_candlestick_week(df: pd.DataFrame, records: pd.DataFrame,
                          optimal_lo: float, optimal_hi: float, ticker: str):
    signal_days = records[
        (records["deviation"] >= optimal_lo) &
        (records["deviation"] <  optimal_hi) &
        (records["bounce_50"] == True)
    ]["date"].tolist()

    if not signal_days:
        signal_days = records[
            (records["deviation"] >= optimal_lo) &
            (records["deviation"] <  optimal_hi)
        ]["date"].tolist()

    if not signal_days:
        print(f"  [chart] No signal days for {ticker}, skipping candlestick.")
        return

    chosen_monday = None
    for sd in sorted(signal_days, reverse=True):
        d  = pd.Timestamp(sd)
        mo = d - timedelta(days=d.weekday())
        week_hits = [x for x in signal_days
                     if mo.date() <= x <= (mo + timedelta(days=4)).date()]
        if week_hits:
            chosen_monday = mo
            break

    if chosen_monday is None:
        print(f"  [chart] No valid week found for {ticker}.")
        return

    week_end = chosen_monday + timedelta(days=5)
    week_df  = df[
        (df.index.date >= chosen_monday.date()) &
        (df.index.date <  week_end.date()) &
        (df.index.hour >= 9) &
        ((df.index.hour < 11) | ((df.index.hour == 11) & (df.index.minute == 0)))
    ].copy()

    if week_df.empty:
        print(f"  [chart] No data for chosen week {chosen_monday.date()} ({ticker}).")
        return

    plot_df = week_df[["open","high","low","close","volume"]].copy()
    plot_df.index.name = "Date"

    signal_series = pd.Series(np.nan, index=plot_df.index)
    target_series = pd.Series(np.nan, index=plot_df.index)
    sl_series     = pd.Series(np.nan, index=plot_df.index)
    ma_series     = week_df["ma200"]

    week_records = records[
        (records["date"] >= chosen_monday.date()) &
        (records["date"] <  week_end.date()) &
        (records["deviation"] >= optimal_lo) &
        (records["deviation"] <  optimal_hi)
    ]

    for _, row in week_records.iterrows():
        ot = row["open_time"]
        if ot in signal_series.index:
            signal_series[ot] = plot_df.loc[ot, "low"] * 0.9995
            t_end = ot + timedelta(minutes=SESSION_END_MIN)
            mask  = (plot_df.index >= ot) & (plot_df.index <= t_end)
            target_series[mask] = row["open_price"] + TICK_TARGET
            sl_series[mask]     = row["open_price"] - STOP_LOSS   # ← NEW SL line

    apds = [
        mpf.make_addplot(ma_series,     color="#e87040", width=1.5),
        mpf.make_addplot(signal_series, type="scatter", markersize=120,
                         marker="^", color="#2ecc71"),
        mpf.make_addplot(target_series, color="#2ecc71", linestyle="--", width=1.2),
        mpf.make_addplot(sl_series,     color="#e74c3c", linestyle="--", width=1.2),
    ]

    mc = mpf.make_marketcolors(up="#2ecc71", down="#e74c3c",
                               edge="inherit", wick="inherit", volume="in")
    s  = mpf.make_mpf_style(
        marketcolors=mc, gridstyle=":", gridcolor="#333",
        facecolor="#1a1a2e", figcolor="#1a1a2e", y_on_right=False,
        rc={"axes.labelcolor":"white","xtick.color":"white",
            "ytick.color":"white","text.color":"white"}
    )

    rr    = TICK_TARGET / STOP_LOSS
    title = (f"{ticker} - {TICKERS[ticker]}  |  Week: {chosen_monday.date()}\n"
             f"▲ = entry  |  Green dashed = +{TICK_TARGET}pt TP  |  "
             f"Red dashed = −{STOP_LOSS}pt SL  |  R:R 1:{rr:.1f}")
    fname = f"{ticker.replace('=','')}_candlestick_week.png"

    fig, _ = mpf.plot(
        plot_df, type="candle", style=s,
        addplot=apds, volume=True,
        title=title, figsize=(18, 9),
        returnfig=True, tight_layout=True,
    )
    fig.savefig(fname, dpi=150, bbox_inches="tight", facecolor="#1a1a2e")
    print(f"  [chart] Candlestick week saved -> {fname}")
    plt.close(fig)



def plot_probability_chart(buckets: pd.DataFrame, optimal: pd.Series, ticker: str):
    fig, ax1 = plt.subplots(figsize=(13, 6))
    fig.patch.set_facecolor("#1a1a2e")
    ax1.set_facecolor("#1a1a2e")

    x      = np.arange(len(buckets))
    colors = ["#2ecc71" if row["lo"] == optimal["lo"] else "#3d8bcd"
              for _, row in buckets.iterrows()]

    ax1.bar(x, buckets["win_rate_%"], width=0.6, color=colors, alpha=0.85, zorder=3)
    ax1.set_xticks(x)
    ax1.set_xticklabels(buckets["deviation_bucket"], rotation=45,
                        ha="right", fontsize=8, color="white")
    ax1.set_ylabel(f"Win Rate % (TP +{TICK_TARGET}pts / SL −{STOP_LOSS}pts)",
                   color="white", fontsize=10)
    ax1.tick_params(colors="white")
    ax1.set_xlabel("% Deviation Below 200 MA at 9:30 ET Open", color="white", fontsize=10)
    ax1.grid(axis="y", alpha=0.3, color="white")

    ax2 = ax1.twinx()
    ax2.plot(x, buckets["n_days"], color="#e87040", linewidth=2,
             marker="o", markersize=5)
    ax2.set_ylabel("Sample Days (n)", color="#e87040", fontsize=10)
    ax2.tick_params(colors="#e87040")
    ax2.set_facecolor("#1a1a2e")

    opt_rows = buckets[buckets["lo"] == optimal["lo"]]
    if not opt_rows.empty:
        i = list(buckets.index).index(opt_rows.index[0])
        ax1.annotate(
            f"OPTIMAL\n{optimal['win_rate_%']:.1f}%",
            xy=(i, optimal["win_rate_%"]),
            xytext=(min(i + 1, len(buckets) - 1), optimal["win_rate_%"] + 4),
            color="#2ecc71", fontsize=9, fontweight="bold",
            arrowprops=dict(arrowstyle="->", color="#2ecc71"),
        )

    ax1.legend(
        handles=[
            mpatches.Patch(color="#2ecc71", label="Optimal bucket"),
            mpatches.Patch(color="#3d8bcd", label="Other buckets"),
            plt.Line2D([0],[0], color="#e87040", marker="o", label="Sample days"),
        ],
        loc="upper right", facecolor="#1a1a2e", labelcolor="white"
    )
    rr = TICK_TARGET / STOP_LOSS
    plt.title(
        f"{ticker} - {TICKERS[ticker]}\n"
        f"Bounce Probability by Opening Deviation from 200 MA  "
        f"(TP +{TICK_TARGET}pts | SL −{STOP_LOSS}pts | R:R 1:{rr:.1f})",
        color="white", fontsize=11
    )
    plt.tight_layout()
    fname = f"{ticker.replace('=','')}_bounce_probability.png"
    plt.savefig(fname, dpi=150, bbox_inches="tight", facecolor="#1a1a2e")
    print(f"  [chart] Bounce probability saved -> {fname}")
    plt.close(fig)



def print_results(buckets: pd.DataFrame, optimal: pd.Series,
                  records: pd.DataFrame, ticker: str):
    total  = len(records)
    below  = len(records[records["deviation"] > 0])
    wins   = records["bounce_50"].sum()
    losses = records["sl_hit"].sum()
    rr     = TICK_TARGET / STOP_LOSS

    print(f"\n{'='*72}")
    print(f"  {TICKERS[ticker]} ({ticker})")
    print(f"  {YEARS_BACK}yr  |  5m candles  |  9:30-10:30 ET  |  "
          f"TP: +{TICK_TARGET}pts  |  SL: −{STOP_LOSS}pts  |  R:R 1:{rr:.1f}")
    print(f"{'='*72}")
    print(f"  Total trading days  : {total}")
    print(f"  Days opened below MA: {below}  ({below/total*100:.1f}%)")
    print(f"  Total wins          : {wins}")
    print(f"  Total losses        : {losses}\n")

    display = buckets[[
        "deviation_bucket","n_days","wins","losses","win_rate_%",
        "avg_max_up_pts","avg_max_dn_pts"
    ]].copy()
    display.columns = [
        "Deviation Bucket","Days","Wins","Losses","Win Rate %",
        "Avg Max Up pts","Avg Max Dn pts"
    ]
    print(tabulate(display, headers="keys", tablefmt="rounded_outline",
                   showindex=False, floatfmt=".1f"))

    print(f"\n  OPTIMAL BUCKET   : {optimal['deviation_bucket']}")
    print(f"  Sample days      : {int(optimal['n_days'])}")
    print(f"  Wins             : {int(optimal['wins'])}")
    print(f"  Losses           : {int(optimal['losses'])}")
    print(f"  Win rate         : {optimal['win_rate_%']:.1f}%")
    print(f"  Avg max up (1hr) : {optimal['avg_max_up_pts']:.1f} pts")
    print(f"  Avg max dn (1hr) : {optimal['avg_max_dn_pts']:.1f} pts\n")



def live_signal_check(df: pd.DataFrame, optimal: pd.Series, ticker: str):
    now_et   = datetime.now(ET)
    today_df = df[df.index.date == now_et.date()]
    open_c   = today_df[
        (today_df.index.hour == OPEN_HOUR_ET) &
        (today_df.index.minute == OPEN_MIN_ET)
    ]
    if open_c.empty:
        print(f"  [live] {ticker}: No 9:30 candle yet today ({now_et.date()})\n")
        return

    row = open_c.iloc[0]
    dev = row["pct_below_ma"]
    lo, hi = optimal["lo"], optimal["hi"]
    rr     = TICK_TARGET / STOP_LOSS

    print(f"  LIVE CHECK — {ticker}  ({now_et.strftime('%Y-%m-%d %H:%M ET')})")
    print(f"  9:30 close : {row['close']:.2f}")
    print(f"  200 MA     : {row['ma200']:.2f}")
    print(f"  % below MA : {dev:.3f}%")
    print(f"  Opt zone   : {lo:.2f}% - {hi:.2f}%")
    if lo <= dev < hi:
        print(f"  >> SIGNAL  : {optimal['win_rate_%']:.1f}% win rate  |  R:R 1:{rr:.1f}")
        print(f"     Entry   : {row['close']:.2f}")
        print(f"     Target  : {row['close'] + TICK_TARGET:.2f}  (+{TICK_TARGET}pts)")
        print(f"     Stop    : {row['close'] - STOP_LOSS:.2f}  (−{STOP_LOSS}pts)")
    elif dev > 0:
        print(f"  >> Below MA but NOT in optimal zone")
    else:
        print(f"  >> Price ABOVE 200 MA — no signal")
    print()



def write_readme(results_summary: dict):
    rr    = TICK_TARGET / STOP_LOSS
    lines = [
        "# Futures 200 MA Open-Deviation Bounce Backtest",
        "",
        f"**Strategy:** At the 9:30 ET open, if price is below the {MA_PERIOD}-period MA "
        f"by a threshold %, go long.",
        f"- **Take Profit:** +{TICK_TARGET} points",
        f"- **Stop Loss:** −{STOP_LOSS} points",
        f"- **Risk:Reward:** 1:{rr:.1f}",
        f"- **Session window:** 9:30–10:30 ET (5-minute candles)",
        "",
        "## Instruments",
        "- NQ=F (Nasdaq 100 Futures)",
        "- YM=F (Dow Jones Futures)",
        "",
        "## Results Summary",
        "",
        "| Ticker | Optimal Dev Bucket | Win Rate | Sample Days |",
        "|--------|--------------------|----------|-------------|",
    ]
    for ticker, info in results_summary.items():
        lines.append(f"| {ticker} | {info.get('bucket','?')} | "
                     f"{info.get('win_rate','?')}% | {info.get('n','?')} |")

    lines += [
        "",
        "## Charts per Ticker",
        "- `*_trade_overview.png` — all trade entries/exits across the backtest period",
        "- `*_single_day_detail.png` — zoomed single-day candlestick with entry/TP/SL",
        "- `*_win_rate_by_deviation.png` — win rate by deviation bucket (with 30pt SL)",
        "- `*_candlestick_week.png` — sample week with signal overlays",
        "- `*_bounce_probability.png` — original probability chart",
        "- `backtest_results_*.csv` — full daily trade log",
        "",
        "## How to Run",
        "```bash",
        "pip install yfinance mplfinance pandas numpy tabulate pytz matplotlib",
        "python futures_ma200_open_bounce.py",
        "```",
        "",
        f"*Auto-generated {datetime.now().strftime('%Y-%m-%d %H:%M')}*",
    ]

    with open("README.md", "w") as f:
        f.write("\n".join(lines))
    print("  [readme] README.md written")



def push_to_github(results_summary: dict):
    if GITHUB_TOKEN in ("YOUR_TOKEN_HERE", ""):
        print("\n[github] Skipping push — set GITHUB_TOKEN in CONFIG first.\n")
        return

    remote_url = f"https://{GITHUB_TOKEN}@github.com/{GITHUB_REPO}.git"
    cwd        = os.getcwd()

    # ── Write THIS source to cwd so it gets committed ───────
    # Collects source of every function via inspect — works in .py AND Colab.
    import inspect
    script_dst = os.path.join(cwd, "futures_ma200_open_bounce.py")
    _fn_names = [
        "install", "fetch_chunked", "add_ma", "build_open_records",
        "analyse_buckets", "find_optimal_bucket",
        "plot_trade_overview", "plot_single_day",
        "plot_win_rate_chart", "plot_candlestick_week",
        "plot_probability_chart", "print_results",
        "live_signal_check", "write_readme",
        "push_to_github", "get_user_config", "run",
    ]
    _globs  = globals()
    _pieces = ["# futures_ma200_open_bounce.py  (auto-saved by push_to_github)\n"]
    for _name in _fn_names:
        _obj = _globs.get(_name)
        if callable(_obj):
            try:
                _pieces.append(inspect.getsource(_obj))
                _pieces.append("\n")
            except Exception:
                pass
    try:
        with open(script_dst, "w") as _f:
            _f.write("\n".join(_pieces))
        print(f"  [github] Source written -> {script_dst}")
    except Exception as _e:
        print(f"  [github] Could not write source: {_e}")

    def run_git(args, check=True):
        result = subprocess.run(
            ["git"] + args, cwd=cwd,
            capture_output=True, text=True
        )
        if check and result.returncode != 0:
            print(f"  [git warn] {' '.join(args)}: {result.stderr.strip()}")
        return result

    print("\n[github] Preparing push ...")

    if not os.path.exists(os.path.join(cwd, ".git")):
        run_git(["init"])
        run_git(["checkout", "-b", GITHUB_BRANCH])

    run_git(["remote", "set-url", "origin", remote_url], check=False)
    r = run_git(["remote", "get-url", "origin"], check=False)
    if r.returncode != 0:
        run_git(["remote", "add", "origin", remote_url])

    run_git(["config", "user.email", "bot@futures-backtest"])
    run_git(["config", "user.name",  "FuturesBacktest"])

    staged = []
    for fname in OUTPUT_FILES:
        fpath = os.path.join(cwd, fname)
        if os.path.exists(fpath):
            run_git(["add", fname])
            staged.append(fname)

    if not staged:
        print("  [github] Nothing to commit.")
        return

    rr        = TICK_TARGET / STOP_LOSS
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    summary_lines = []
    for ticker, info in results_summary.items():
        summary_lines.append(
            f"{ticker}: {info.get('bucket','?')} → "
            f"{info.get('win_rate','?')}% win rate  (R:R 1:{rr:.1f})"
        )
    commit_msg = (
        f"Futures MA200 backtest {timestamp}\n\n"
        + "\n".join(summary_lines)
    )

    run_git(["commit", "-m", commit_msg])
    result = run_git(
        ["push", "--set-upstream", "origin", GITHUB_BRANCH],
        check=False
    )

    if result.returncode == 0:
        print(f"  [github] ✓ Pushed {len(staged)} files to "
              f"github.com/{GITHUB_REPO} ({GITHUB_BRANCH})")
        for f in staged:
            print(f"    + {f}")
    else:
        print(f"  [github] Push failed: {result.stderr.strip()}")
        print("  Check your token has 'repo' scope and hasn't expired.")
        print("  Generate at: github.com → Settings → Developer Settings → PAT (classic)")
    print()



def get_user_config():
    print("\n" + "="*60)
    print("  FUTURES MA200 BOUNCE STUDY — SETUP")
    print("="*60)
    print("  Press Enter to accept the default [value]\n")

    print("── GitHub ──────────────────────────────────────────")
    token = input("  GitHub Personal Access Token (needs repo scope)\n  Token : ").strip()
    if not token:
        token = "YOUR_TOKEN_HERE"

    repo = input("  GitHub repo  [hlenganeindustries-alt/stock-ranker] : ").strip()
    if not repo:
        repo = "hlenganeindustries-alt/stock-ranker"

    branch = input("  Branch  [main] : ").strip()
    if not branch:
        branch = "main"

    print("\n── Instruments ─────────────────────────────────────")
    print("  Default: NQ=F (Nasdaq Futures), YM=F (Dow Futures)")
    custom  = input("  Add extra tickers? (comma-separated, or Enter to skip) : ").strip()
    tickers = {"NQ=F": "Nasdaq 100 Futures", "YM=F": "Dow Jones Futures"}
    if custom:
        for t in [x.strip().upper() for x in custom.split(",") if x.strip()]:
            tickers[t] = t

    print("\n── Backtest Parameters ─────────────────────────────")
    raw       = input("  MA period  [200] : ").strip()
    ma_period = int(raw) if raw.isdigit() else 200

    raw         = input(f"  Take-profit in points  [{TICK_TARGET}] : ").strip()
    tick_target = int(raw) if raw.isdigit() else TICK_TARGET

    raw       = input(f"  Stop-loss in points  [{STOP_LOSS}] : ").strip()
    stop_loss = int(raw) if raw.isdigit() else STOP_LOSS

    raw        = input("  Years of history  [3] : ").strip()
    years_back = int(raw) if raw.isdigit() else 3

    raw         = input("  Session window minutes after open  [90] : ").strip()
    session_end = int(raw) if raw.isdigit() else 90

    raw = input("  Deviation bucket size %  [0.25] : ").strip()
    try:
        bucket_size = float(raw) if raw else 0.25
    except ValueError:
        bucket_size = 0.25

    raw = input("  Max deviation % to analyse  [3.0] : ").strip()
    try:
        max_dev = float(raw) if raw else 3.0
    except ValueError:
        max_dev = 3.0

    raw         = input("  Minimum sample days per bucket  [10] : ").strip()
    min_samples = int(raw) if raw.isdigit() else 10

    print("\n── Data Source ─────────────────────────────────────")
    print("  yfinance gives ~60 days of 5m data.")
    print("  For a full 3-year backtest, enter a Polygon.io API key.")
    print("  Free key at polygon.io  (or press Enter to use yfinance)")
    polygon_key = input("  Polygon.io API key (optional) : ").strip()

    rr = tick_target / stop_loss
    print("\n" + "="*60)
    print("  CONFIGURATION SUMMARY")
    print("="*60)
    print(f"  GitHub repo   : {repo}  (branch: {branch})")
    print(f"  GitHub token  : {'SET' if token != 'YOUR_TOKEN_HERE' else 'NOT SET — push skipped'}")
    print(f"  Instruments   : {', '.join(tickers.keys())}")
    print(f"  MA period     : {ma_period}")
    print(f"  Take-profit   : +{tick_target} pts")
    print(f"  Stop-loss     : −{stop_loss} pts")
    print(f"  R:R           : 1:{rr:.1f}")
    print(f"  History       : {years_back} year(s)")
    print(f"  Data source   : {'Polygon.io' if polygon_key else 'yfinance (~60 days only)'}")
    print(f"  Session window: 9:30 + {session_end} min")
    print(f"  Bucket size   : {bucket_size}%  |  Max dev: {max_dev}%  |  Min samples: {min_samples}")
    print("="*60)

    confirm = input("\n  Start backtest? [Y/n] : ").strip().lower()
    if confirm == "n":
        print("  Cancelled.")
        raise SystemExit(0)

    return {
        "GITHUB_TOKEN":    token,
        "GITHUB_REPO":     repo,
        "GITHUB_BRANCH":   branch,
        "TICKERS":         tickers,
        "MA_PERIOD":       ma_period,
        "TICK_TARGET":     tick_target,
        "STOP_LOSS":       stop_loss,
        "YEARS_BACK":      years_back,
        "SESSION_END_MIN": session_end,
        "BUCKET_SIZE":     bucket_size,
        "MAX_DEV":         max_dev,
        "MIN_SAMPLES":     min_samples,
        "POLYGON_KEY":     polygon_key,
    }



def run():
    cfg = get_user_config()

    global GITHUB_TOKEN, GITHUB_REPO, GITHUB_BRANCH, TICKERS
    global MA_PERIOD, TICK_TARGET, STOP_LOSS, YEARS_BACK, SESSION_END_MIN
    global BUCKET_SIZE, MAX_DEV, MIN_SAMPLES

    GITHUB_TOKEN    = cfg["GITHUB_TOKEN"]
    GITHUB_REPO     = cfg["GITHUB_REPO"]
    GITHUB_BRANCH   = cfg["GITHUB_BRANCH"]
    TICKERS         = cfg["TICKERS"]
    MA_PERIOD       = cfg["MA_PERIOD"]
    TICK_TARGET     = cfg["TICK_TARGET"]
    STOP_LOSS       = cfg["STOP_LOSS"]
    YEARS_BACK      = cfg["YEARS_BACK"]
    SESSION_END_MIN = cfg["SESSION_END_MIN"]
    BUCKET_SIZE     = cfg["BUCKET_SIZE"]
    MAX_DEV         = cfg["MAX_DEV"]
    MIN_SAMPLES     = cfg["MIN_SAMPLES"]

    rr = TICK_TARGET / STOP_LOSS
    print(f"\n  Futures 200 MA Open Deviation — Bounce Study")
    print(f"  Instruments : {', '.join(TICKERS.keys())}")
    print(f"  Interval    : {INTERVAL}  |  MA: {MA_PERIOD}  |  "
          f"TP: +{TICK_TARGET}pts  |  SL: −{STOP_LOSS}pts  |  R:R 1:{rr:.1f}")
    print(f"  Window      : 9:30-10:30 ET  |  History: ~{YEARS_BACK} years\n")

    results_summary = {}

    for ticker in TICKERS:
        try:
            # 1. Fetch data
            raw = fetch_chunked(ticker)

            # 2. MA + deviation
            df = add_ma(raw)
            print(f"  Candles with valid 200 MA : {len(df):,}")

            # 3. Daily records (with SL tracking)
            rec_df  = build_open_records(df)
            records = rec_df.to_dict("records")
            print(f"  Trading days found        : {len(records)}")

            # 4. Bucket analysis
            buckets = analyse_buckets(rec_df)
            if buckets.empty:
                print(f"  [warn] No buckets for {ticker}\n")
                continue

            # 5. Optimal bucket
            optimal = find_optimal_bucket(buckets)

            # 6. Print table
            print_results(buckets, optimal, rec_df, ticker)

            # 7. Live check
            live_signal_check(df, optimal, ticker)

            # 8a. NEW: Multi-day trade overview chart
            signal_recs = [r for r in records if r["deviation"] > 0]
            plot_trade_overview(df, signal_recs, ticker)

            # 8b. NEW: Single-day detail (best win day)
            best_win  = next((r for r in records if r["outcome"] == "win"), None)
            best_loss = next((r for r in records if r["outcome"] == "loss"), None)
            if best_win:
                plot_single_day(df, best_win, ticker, suffix="_win")
            if best_loss:
                plot_single_day(df, best_loss, ticker, suffix="_loss")
            # rename to standard name for GitHub
            for suf in ["_win", "_loss"]:
                src = f"{ticker.replace('=','')}_single_day_detail{suf}.png"
                dst = f"{ticker.replace('=','')}_single_day_detail.png"
                if os.path.exists(src):
                    os.replace(src, dst)
                    break

            # 8c. NEW: Win-rate by deviation bucket (with 30pt SL)
            plot_win_rate_chart(buckets, optimal, ticker)

            # 8d. Original charts kept
            plot_probability_chart(buckets, optimal, ticker)
            plot_candlestick_week(df, rec_df, optimal["lo"], optimal["hi"], ticker)

            # 9. Save CSV
            csv_name = f"backtest_results_{ticker.replace('=','')}.csv"
            rec_df.to_csv(csv_name, index=False)
            print(f"  [csv] Saved -> {csv_name}")

            results_summary[ticker] = {
                "bucket":   optimal["deviation_bucket"],
                "win_rate": optimal["win_rate_%"],
                "n":        int(optimal["n_days"]),
            }

        except Exception as e:
            import traceback
            print(f"\n[error] {ticker}: {e}")
            traceback.print_exc()

    # 10. Write README
    write_readme(results_summary)

    # 11. Push everything (including this source file) to GitHub
    push_to_github(results_summary)

    print("Done.\n")
    print("Output files per ticker:")
    print("  *_trade_overview.png       — all trades with entry/TP/SL markers + dates")
    print("  *_single_day_detail.png    — zoomed single day candlestick")
    print("  *_win_rate_by_deviation.png — win rate buckets (30pt SL applied)")
    print("  *_candlestick_week.png     — sample week with signal overlays")
    print("  *_bounce_probability.png   — original probability chart")
    print("  backtest_results_*.csv     — full daily trade log")
    print("  futures_ma200_open_bounce.py — this source file (also on GitHub)")
    print("  README.md                  — auto-generated summary")


