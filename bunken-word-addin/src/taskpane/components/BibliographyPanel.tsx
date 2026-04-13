type Props = {
  disabled: boolean;
  onRefreshBibliography: () => Promise<void>;
};

export function BibliographyPanel({
  disabled,
  onRefreshBibliography,
}: Props) {
  return (
    <section>
      <h2 style={styles.heading}>参考文献</h2>
      <p style={styles.message}>
        文書内の引用情報を集めて、文末の参考文献ブロックを再生成します。
      </p>
      <button
        type="button"
        disabled={disabled}
        onClick={() => void onRefreshBibliography()}
        style={styles.button}
      >
        参考文献を更新
      </button>
    </section>
  );
}

const styles = {
  heading: {
    margin: "0 0 10px",
    fontSize: "17px",
  },
  message: {
    margin: "0 0 12px",
    fontSize: "12px",
    color: "#52606d",
  },
  button: {
    width: "100%",
    padding: "12px",
    borderRadius: "999px",
    border: "1px solid #1f2937",
    backgroundColor: "#fff7ed",
    color: "#7c2d12",
    fontWeight: 700,
    cursor: "pointer",
  },
};
