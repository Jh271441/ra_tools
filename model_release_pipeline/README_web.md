# Raw Web / Truck / Jenkins Flow

This file records the low-level commands behind the IFX part of the release
pipeline. Use it when you want to bypass the Python CLI and run the same flow
manually.

## 1. Enter A Voyager Environment

`truck.py` is provided by Voyager. Local `assist_stuck` usually does not have it.

Docker mode:

```bash
docker exec -it "${CONTAINER_NAME_GEN4:-my-awesome-devbox-gen4}" /bin/zsh
cd /home/didi/workspace/voyager
source /home/didi/workspace/voyager/bazel/scripts/setup.sh
truck.py --help
```

SSH mode is similar after logging into a machine that already has Voyager:

```bash
ssh cloud_server
cd ~/workspace/voyager
source bazel/scripts/setup.sh
truck.py --help
```

## 2. Upload Or Verify Precision Test Zip

Current configured precision test:

```bash
PRECISION_MODULE="ifx-precision-test"
PRECISION_ZIP_NAME="ifx_fp32_after_scaling_pos1e1_5.zip"
PRECISION_VERSION="1"
PRECISION_ARG="${PRECISION_MODULE} ${PRECISION_ZIP_NAME} -v ${PRECISION_VERSION}"
```

If the zip is already on fileserver, verify it:

```bash
truck.py list "${PRECISION_MODULE}" "${PRECISION_ZIP_NAME}" | head -n 20
```

If you need to upload a new precision test zip, use this raw command. Replace
`PRECISION_TEST_ZIP` with the local path in the Voyager environment:

```bash
PRECISION_TEST_ZIP="/path/to/ifx_fp32_after_scaling_pos1e1_5.zip"

truck.py push "${PRECISION_MODULE}" "${PRECISION_TEST_ZIP}" \
  -v "${PRECISION_VERSION}" \
  --desc "scenario_dnn IFX precision test, fp32 after scaling pos1e1"

truck.py list "${PRECISION_MODULE}" "${PRECISION_ZIP_NAME}" | head -n 20
```

The Jenkins parameter later uses this exact value:

```text
ifx-precision-test ifx_fp32_after_scaling_pos1e1_5.zip -v 1
```

## 3. Upload Or Verify ONNX

Current ONNX used in the run:

```bash
ONNX_MODULE="planner.model-files"
ONNX_NAME="vectorized_scenario_remote_assist_model.onnx"
ONNX_VERSION="65"
ONNX_ARG="${ONNX_MODULE} ${ONNX_NAME} -v ${ONNX_VERSION}"
```

Verify the existing fileserver version:

```bash
truck.py list "${ONNX_MODULE}" "${ONNX_NAME}" | head -n 30
```

Upload a local ONNX from the Voyager environment:

```bash
ONNX_FILE="/path/to/vectorized_scenario_remote_assist_model.onnx"
ONNX_DESC="2026_05_10_finetune_4_tasks_old_data_no_assist_2_nodes, epoch=007, loss_min, alpha=0.75, top4 + randn4, old data."

truck.py push "${ONNX_MODULE}" "${ONNX_FILE}" \
  -v "${ONNX_VERSION}" \
  --desc "${ONNX_DESC}"

truck.py list "${ONNX_MODULE}" "${ONNX_NAME}" | head -n 30
```

Fileserver deduplicates same-name same-md5 uploads. If `truck.py push` says the
file already exists, it may not create the requested new version. In the current
case, re-pushing did not create version `66`; the usable version remained `65`.

## 4. Trigger Jenkins IFX With Curl

These values match the legacy-compatible bs0 flow:

```bash
JENKINS_BASE="http://10.79.18.51:8088"
JENKINS_JOB="voyager_ifxruntime_trt_cached_engines_generator_ov23_trt10_dev"
JENKINS_TOKEN="ONNX2IFX_DEV"
USERNAME="jasperchen"

ONNX_ARG="planner.model-files vectorized_scenario_remote_assist_model.onnx -v 65"
PRECISION_ARG="ifx-precision-test ifx_fp32_after_scaling_pos1e1_5.zip -v 1"

COOKIE_JAR="/tmp/jenkins_ifx_cookie.txt"
HEADER_FILE="/tmp/jenkins_ifx_trigger_headers.txt"
BODY_FILE="/tmp/jenkins_ifx_trigger_body.txt"
```

Fetch Jenkins crumb. This is required because POST without a crumb returns 403:

```bash
CRUMB_JSON="$(curl -sS -c "${COOKIE_JAR}" "${JENKINS_BASE}/crumbIssuer/api/json")"
CRUMB_FIELD="$(printf '%s' "${CRUMB_JSON}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["crumbRequestField"])')"
CRUMB_VALUE="$(printf '%s' "${CRUMB_JSON}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["crumb"])')"
```

Trigger the job. Do not pass `label` by default. The run is tracked by the
Jenkins queue/build URL. `max_batch=0` keeps the output names consistent with the
older `bs0_*` artifacts.

```bash
curl -sS -D "${HEADER_FILE}" -o "${BODY_FILE}" \
  -b "${COOKIE_JAR}" \
  -c "${COOKIE_JAR}" \
  -H "${CRUMB_FIELD}: ${CRUMB_VALUE}" \
  -X POST "${JENKINS_BASE}/job/${JENKINS_JOB}/buildWithParameters" \
  --data-urlencode "token=${JENKINS_TOKEN}" \
  --data-urlencode "username=${USERNAME}" \
  --data-urlencode "truck_py_arguments_of_onnx=${ONNX_ARG}" \
  --data-urlencode "max_batch=0" \
  --data-urlencode "x86_convert=openvino" \
  --data-urlencode "precision_convert=FP16" \
  --data-urlencode "precision_test_file=${PRECISION_ARG}"

cat "${HEADER_FILE}"
cat "${BODY_FILE}"
```

Expected trigger response is normally HTTP `201 Created` or a redirect, with a
`Location` header pointing to a Jenkins queue item.

```bash
QUEUE_URL="$(awk 'tolower($1)=="location:" {print $2}' "${HEADER_FILE}" | tr -d '\r' | tail -n 1)"
echo "QUEUE_URL=${QUEUE_URL}"
```

## 5. Poll Queue Until Build Is Assigned

```bash
while true; do
  QUEUE_JSON="$(curl -sS -b "${COOKIE_JAR}" "${QUEUE_URL%/}/api/json")"
  BUILD_URL="$(printf '%s' "${QUEUE_JSON}" | python3 -c 'import json,sys; data=json.load(sys.stdin); print((data.get("executable") or {}).get("url", ""))')"
  WHY="$(printf '%s' "${QUEUE_JSON}" | python3 -c 'import json,sys; data=json.load(sys.stdin); print(data.get("why") or "")')"
  date '+%F %T'
  echo "queue: ${WHY:-waiting for executable.url}"
  if [ -n "${BUILD_URL}" ]; then
    break
  fi
  sleep 10
done

echo "BUILD_URL=${BUILD_URL}"
```

## 6. Poll Build Until Finished

```bash
while true; do
  BUILD_JSON="$(curl -sS -b "${COOKIE_JAR}" "${BUILD_URL%/}/api/json")"
  BUILDING="$(printf '%s' "${BUILD_JSON}" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("building"))')"
  RESULT="$(printf '%s' "${BUILD_JSON}" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("result"))')"
  BUILD_NUMBER="$(printf '%s' "${BUILD_JSON}" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("number"))')"
  date '+%F %T'
  echo "build_number=${BUILD_NUMBER}; building=${BUILDING}; result=${RESULT}"
  if [ "${BUILDING}" = "False" ] || [ "${BUILDING}" = "false" ]; then
    break
  fi
  sleep 30
done
```

## 7. Download Console And Check Artifacts

```bash
CONSOLE_FILE="/tmp/jenkins_ifx_console_${BUILD_NUMBER}.txt"
curl -sS -b "${COOKIE_JAR}" "${BUILD_URL%/}/consoleText" -o "${CONSOLE_FILE}"

grep -E "本次执行转换的onnx|本次转换的ifxmodel|upload done|upload failed|Finished:" "${CONSOLE_FILE}"
grep -E "planner.model-files .*\\.ifxmodel" "${CONSOLE_FILE}"
```

Expected source ONNX:

```text
planner.model-files vectorized_scenario_remote_assist_model.onnx -v 65
```

Expected IFX artifacts for the old flow are `bs0`, including thor:

```text
vectorized_scenario_remote_assist_model_bs0_fp32_x86.ifxmodel
vectorized_scenario_remote_assist_model_bs0_fp16_6000_trt109.ifxmodel
vectorized_scenario_remote_assist_model_bs0_fp16_3060_trt109.ifxmodel
vectorized_scenario_remote_assist_model_bs0_fp16_gen4_trt109.ifxmodel
vectorized_scenario_remote_assist_model_bs0_fp16_thor_trt1013.ifxmodel
```

Treat the conversion as failed if any expected platform is missing or if the
console contains `upload failed`, even when Jenkins ends with `Finished: SUCCESS`.
The recent failed case was:

```text
vectorized_scenario_remote_assist_model_bs1_fp16_thor_trt1013.ifxmodel upload failed
```

## 8. Equivalent CLI Commands

The Python CLI wraps the same operations:

```bash
python -m model_release_pipeline.cli upload \
  --run-id 20260512_134214_551939 \
  --onnx-version 65 \
  --desc "loss_min, alpha=0.75, top4 + randn4, old data"

python -m model_release_pipeline.cli ifx-convert \
  --run-id 20260512_134214_551939
```

The CLI default now matches this raw flow: POST with crumb, token
`ONNX2IFX_DEV`, `max_batch=0`, no injected `scenario_dnn_release_*` label, and
Jenkins queue/build URL as the durable run handle.
