# 릴리스 절차서 (RELEASING.md)

Volo 새 버전을 **GitHub Releases 에 버전별 zip(`Volo-windows.zip`)으로 올려** 비개발자가
받아 바로 실행하게 하는 절차입니다. 핵심 경로는 **태그 푸시 → GitHub Actions 자동 빌드**이며,
`gh` CLI 없이 **웹 UI**로 올리는 대안과 **로컬 수동 빌드** 대안도 함께 적습니다.

> 빌드 산출물은 `dist/Volo/Volo.exe`(onedir)이고, 배포 단위는 그 폴더를 통째로 압축한
> `Volo-windows.zip`(약 158MB)입니다. 모델 가중치는 동봉하지 않으며 `.exe` 최초 실행 시
> 자동 다운로드됩니다.

---

## 0. 사전 준비 (최초 1회)

- 아직 git 저장소가 아니라면 초기화하고 GitHub 원격을 연결합니다.
  ```bash
  git init
  git add .
  git commit -m "chore: initial commit"
  git branch -M main
  git remote add origin https://github.com/<OWNER>/<REPO>.git
  git push -u origin main
  ```
- `.github/workflows/release.yml` 이 저장소에 포함돼 푸시돼 있어야 자동 빌드가 동작합니다.
- (선택) `gh` CLI 를 쓰려면 설치: `winget install GitHub.cli` → `gh auth login`.
  설치하지 않아도 아래 **B(웹 UI)** 경로로 릴리스할 수 있습니다.

---

## 1. 버전 정하기

1. **버전 번호 확정** — SemVer 규칙(아래 5장)에 따라 `X.Y.Z` 를 정합니다.
2. **`pyproject.toml` 의 `[project].version` 갱신** — 예: `version = "0.1.0"`.
   ```toml
   [project]
   name = "volo"
   version = "0.1.0"
   ```
3. **`CHANGELOG.md` 갱신** — `[Unreleased]` 에 쌓아둔 변경을 새 버전 섹션으로 내립니다.
   - `## [Unreleased]` 아래 항목을 `## [X.Y.Z] - YYYY-MM-DD` 로 옮기고,
   - 비워진 `[Unreleased]` 는 그대로 유지(다음 변경 누적용),
   - 문서 하단 비교 링크가 있으면 함께 갱신합니다.
4. **커밋** — 버전과 체인지로그 갱신을 하나의 커밋으로:
   ```bash
   git add pyproject.toml CHANGELOG.md
   git commit -m "release: v0.1.0"
   git push
   ```

> 태그는 버전 커밋이 푸시된 **이후**에 답니다(태그가 가리키는 커밋에 버전/체인지로그가
> 반영돼 있어야 함).

---

## 2. (권장) 태그 푸시 → 자동 빌드 · 자동 첨부

가장 단순한 정식 경로입니다. 태그 `vX.Y.Z` 를 푸시하면
[`.github/workflows/release.yml`](.github/workflows/release.yml) 이
**깨끗한 windows-latest 러너**에서 빌드하고 결과물을 Release 에 자동으로 붙입니다.

```bash
git tag v0.1.0
git push --tags
```

워크플로가 자동으로 수행하는 일:
1. `test` 잡 — `pip install -e ".[dev]"` 후 `pytest -q` (faster-whisper/ffmpeg 불필요한 결정적 모듈).
2. `build-windows` 잡 — `pip install -e ".[app,build]"` → `pyinstaller packaging/volo.spec` 로 `dist/Volo/Volo.exe` 생성.
3. `LICENSE` / `THIRD_PARTY_NOTICES.md` 를 `dist/Volo/` 에 동봉.
4. `dist/Volo/*` 를 `Volo-windows.zip` 으로 압축.
5. 태그 푸시인 경우 `softprops/action-gh-release` 가 해당 태그의 **Release 를 만들고 `Volo-windows.zip` 을 에셋으로 첨부**.

**확인** — GitHub 저장소 → **Actions** 탭에서 `release` 워크플로가 초록불인지,
→ **Releases** 탭에 `v0.1.0` 릴리스와 `Volo-windows.zip` 에셋이 올라왔는지 확인합니다.
릴리스 본문(설명)은 자동 생성 초안이므로, 필요하면 **Releases → Edit** 에서
해당 버전의 CHANGELOG 내용을 붙여 다듬습니다.

> `workflow_dispatch` 도 지원하므로 Actions 탭에서 수동 실행해 **빌드 산출물(artifact)** 만
> 받아볼 수도 있습니다(이 경우 태그가 없으므로 Release 자동 첨부는 일어나지 않음 → 아래 B/C 로 수동 업로드).

### 자동 빌드가 실패하면
- **Actions 로그를 코드 레벨로 확인**합니다(어느 잡/스텝에서 멈췄는지).
- `pyinstaller packaging/volo.spec` 단계 실패가 잦습니다. spec 은 검증된 초안이지만 의존성
  버전에 따라 hidden import / 데이터 동봉(`assets/presets`)에서 문제가 날 수 있습니다 →
  로컬에서 동일 명령으로 재현해 원인을 좁힌 뒤 spec/pyproject 를 고쳐 다시 태그하거나,
  급할 때는 아래 **C(로컬 수동 빌드)** 로 zip 을 만들어 **B(웹 UI)** 로 직접 올립니다.
- 잘못 단 태그를 지우고 다시 달기:
  ```bash
  git push --delete origin v0.1.0   # 원격 태그 삭제
  git tag -d v0.1.0                 # 로컬 태그 삭제
  # 수정 후 다시: git tag v0.1.0 && git push --tags
  ```

---

## 3. 대안 B — `gh` CLI 없이 GitHub 웹 UI 로 릴리스 만들기

자동 첨부가 안 됐거나(예: `workflow_dispatch` 로만 빌드) 수동으로 올리고 싶을 때.

1. **zip 확보** — Actions 의 `Volo-windows` artifact 를 내려받거나(다운로드하면 `Volo-windows.zip`),
   또는 아래 **C** 로 로컬 빌드한 `Volo-windows.zip` 을 준비합니다.
   (Actions artifact 는 zip 안에 zip 형태로 받아질 수 있으니, 압축을 한 번 풀어 안쪽 `Volo-windows.zip` 을 꺼내세요.)
2. GitHub 저장소 → **Releases** → **Draft a new release**(또는 **Create a new release**).
3. **Choose a tag** — `v0.1.0` 입력.
   - 태그가 이미 있으면 선택만,
   - 없으면 "Create new tag: v0.1.0 on publish" 로 새로 만들고 Target 브랜치(보통 `main`) 선택.
4. **Release title** — `v0.1.0`.
5. **본문** — `CHANGELOG.md` 의 해당 버전 섹션 내용을 붙여넣습니다.
6. **Attach binaries** — "Attach binaries by dropping them here or selecting them" 영역에
   `Volo-windows.zip` 을 끌어다 놓아 업로드합니다.
7. **Publish release**.

> 웹 UI 에서 태그를 새로 만들면(2장처럼 별도로 `git push --tags` 하지 않은 경우) 자동 빌드
> 워크플로가 그 태그로 다시 트리거될 수 있습니다. 이미 zip 을 수동 첨부했다면 중복 빌드는
> 무시하거나, 자동 빌드 결과로 에셋을 교체해도 됩니다.

---

## 4. 대안 C — 로컬 수동 빌드 → zip 만들어 업로드

러너 없이 내 Windows 머신에서 직접 만드는 경로(자동 빌드가 막혔을 때의 비상/검증용).

```bash
# 1) 빌드 의존성 설치 (GUI + PyInstaller)
pip install -e ".[app,build]"

# 2) onedir 빌드 → dist/Volo/Volo.exe
pyinstaller packaging/volo.spec

# 3) (권장) 라이선스 고지 동봉
cp LICENSE dist/Volo/LICENSE.txt
cp THIRD_PARTY_NOTICES.md dist/Volo/THIRD_PARTY_NOTICES.md
```

```powershell
# 4) dist/Volo 폴더 통째로 압축 → Volo-windows.zip
Compress-Archive -Path dist/Volo/* -DestinationPath Volo-windows.zip
```

**빌드 직후 점검(중요):**
- `dist/Volo/Volo.exe` 더블클릭 → GUI 가 뜨는지.
- 짧은 영상으로 자막 생성 E2E(최초 모델 다운로드 → 전사 → 내보내기)가 되는지.
- 스타일 프리셋(`assets/presets`) 이 frozen 모드에서 로딩되는지.
- LGPL 동봉 파일(`LICENSE.txt`, `THIRD_PARTY_NOTICES.md`)이 포함됐는지.

만든 `Volo-windows.zip` 은 **B(웹 UI)** 6번 단계로 Release 에 첨부합니다.
(`gh` CLI 가 설치돼 있다면: `gh release create v0.1.0 Volo-windows.zip --title v0.1.0 --notes-file CHANGELOG.md` 한 줄로도 가능.)

---

## 5. 버전 규칙 (SemVer)

`MAJOR.MINOR.PATCH` (예: `0.1.0`).

- **MAJOR** — 하위 호환이 깨지는 변경(출력 포맷/CLI 옵션/엔진 인터페이스 비호환 변경 등).
- **MINOR** — 하위 호환되는 기능 추가(새 옵션·새 내보내기 포맷·번역 백엔드 추가 등).
- **PATCH** — 하위 호환되는 버그 수정·문서/패키징 보정.

추가 규칙:
- `0.y.z` (0.x 대) 는 **초기 개발 단계**로, MINOR 에서도 호환이 깨질 수 있습니다.
  안정 API 를 공표할 준비가 되면 `1.0.0` 으로 올립니다.
- 사전 릴리스는 접미사로 표기: `1.0.0-rc.1`, `0.2.0-beta.1`.
- 태그는 항상 `v` 접두사: 버전 `0.1.0` → 태그 `v0.1.0`.
- `pyproject.toml` 의 `version` 과 태그 번호는 **항상 일치**시킵니다.

---

## 한눈에 보는 체크리스트

- [ ] `pyproject.toml` `[project].version` 갱신
- [ ] `CHANGELOG.md` 의 `[Unreleased]` → `[X.Y.Z] - YYYY-MM-DD` 정리
- [ ] `release: vX.Y.Z` 커밋 & push
- [ ] `git tag vX.Y.Z && git push --tags`
- [ ] Actions `release` 워크플로 초록불 확인
- [ ] Releases 에 `vX.Y.Z` + `Volo-windows.zip` 에셋 확인
- [ ] (필요 시) Release 본문에 CHANGELOG 내용 붙여 다듬기
- [ ] 다운로드 → 압축 해제 → `Volo.exe` 실행으로 최종 스모크 테스트
