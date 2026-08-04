import redteam_drift as d
import hashlib

data = d.load_eval_set()
def bad_judge(attack_prompt, target_response):
    for ex in data["examples"]:
        if ex["target_response"] == target_response:
            h = int(hashlib.md5(ex["id"].encode()).hexdigest(), 16)
            if h % 10 < 4:
                wrong = {"FAIL":"SUCCESS","PARTIAL":"FAIL","SUCCESS":"FAIL"}
                return wrong[ex["ground_truth"]]
            return ex["ground_truth"]
    return "FAIL"

result = d.run_judge_eval(call_evaluate_fn=bad_judge, model="degraded")
alert = d.check_drift(result)
print(f"Accuracy: {result['accuracy']:.1%}")
print(f"Drift detected: {alert['drifted']}")
for r in alert["reasons"]:
    print("  ALERT:", r)