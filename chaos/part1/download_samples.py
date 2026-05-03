"""Download CSV samples from Drive into samples/<subfolder>/."""
import os
import gdown

BASE = os.path.dirname(os.path.abspath(__file__))

FILES = {
    "square": [
        ("13cMtHdkbd8k1hAgaWhJHU1mntgMPZxua", "V_900mV_res_500mV.csv"),
        ("1X1E_3qbgvj--uyrzDUVwNtqGS0C0ZQ5b", "V_8000mV_res_5V.csv"),
        ("1tOsGcfTQQ0B1-ktM6oym5MJqhDw4KLxe", "V_700mV_res_500mV.csv"),
        ("11aclMebfZcA9VUQpnL-p2x_lRvWX5KtW", "V_6000mV_res_2V.csv"),
        ("1VSADQkwm0cit9asKCQM13_93EfaBgGwl", "V_50mV_res_20mV.csv"),
        ("1YTGdq4xvtFqkJWnEcBigMi5nxm8oNy5I", "V_500mV_res_200mV.csv"),
        ("11Ugnq7OOaQFom5sBufcijJzTMUPoMR1j", "V_4000mV_res_2V.csv"),
        ("1x1voMgp70XXKCD71gCtOmfHSbWwElRtC", "V_2900mV_res_1V.csv"),
        ("11A4C4xvdA1FK9RbV6UNoiXJJUCmgLSfc", "V_2400mV_res_1V.csv"),
        ("1X0wag0f9DtHJGGlHR02sS3QvoTQwyU5V", "V_1900mV_res_500mV.csv"),
        ("1S7_Y_zjSzSJpNKnWWKu1jKQCbb_bXhJs", "V_1600mV_res_500mV.csv"),
        ("1kxYBvdEWKvarDgg32YaMWAUbSBWmlTNC", "V_1400mV_res_500mV.csv"),
        ("1UJDgqYoNyuga_q4XxNQqtZbwigKdn8X-", "V_1100mV_res_500mV.csv"),
        ("1QM7pq7KDmAKzrRXDbjb9dFgcynice7U3", "V_10000mV_res_5V.csv"),
    ],
    "triangle": [
        ("1NOSpub7P6YBBzgxD-1bfoxT9YQ6-YuZz", "f_6.6kHz_V_1.6V_res_500mV.csv"),
        ("1UyhuWDZ48cH2oxFC1RN_ks-AIc6DdQbc", "f_100Hz_V_10V_res_5V.csv"),
        ("1iK8xpTEGY7-6rZx8Rh6NIXeFCOPLtYx1", "f_100Hz_V_1.8V_res_500mV.csv"),
    ],
    "square discharge": [
        ("1GEd5oFNQrQ4LiI3c2F0KOtxsuhMnfGXZ", "v_8V_res_5V_noOff.csv"),
        ("12A1LTVBqRbkm--zIc_RlXGZzk5USaThQ", "v_6V_res_2V_noOff.csv"),
        ("1HlnQB4gO5ZhWTnVVJVDuX6njy0WzyYI3", "v_4V_res_5V.csv"),
        ("1LcRGYqpv9W0zdmL9-brsR_O_3dG_ufb4", "v_400mV_res_500mV.csv"),
        ("1fF1G82X-HQclOde_bUhP-OjCb_eikDog", "v_2.8V_res_2V.csv"),
        ("1MUiSppYcbFBrWDyfyWGVLl3iTF_eXet-", "v_1V_res_1V.csv"),
        ("1-p9dlWEt6G3EDp4XP6lk1V_GkwsimBRJ", "v_10V_res_5V_noOff.csv"),
        ("1lSOP2G-u9tYUAQn-ZkYc2B7JA3f55Gyw", "v_1.6V_res_2V.csv"),
    ],
}


def main():
    for subfolder, files in FILES.items():
        outdir = os.path.join(BASE, "samples", subfolder)
        os.makedirs(outdir, exist_ok=True)
        for fid, name in files:
            outpath = os.path.join(outdir, name)
            if os.path.exists(outpath) and os.path.getsize(outpath) > 1_000_000:
                print(f"SKIP {subfolder}/{name} (already present)")
                continue
            url = f"https://drive.google.com/uc?id={fid}"
            print(f"GET  {subfolder}/{name}")
            try:
                gdown.download(url, outpath, quiet=True)
            except Exception as e:
                print(f"  FAIL: {e}")


if __name__ == "__main__":
    main()
