from redteam_drift import run_judge_eval, check_drift
result = run_judge_eval()          # uses real gpt-4o via redteam_core
print(f"Real judge accuracy: {result['accuracy']:.1%}")
print("Per category:", result["per_category"])
alert = check_drift(result)
print("Drifted:", alert["drifted"], alert["reasons"])