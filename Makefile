.PHONY: run test lint icon ffmpeg dist notarize clean-dist
run:
	uv run python -m cr8txxx
test:
	uv run pytest -q
lint:
	uv run ruff check src tests && uv run ruff format --check src tests
icon:
	uv run python packaging/make_icon.py

# The app is built outside the project (iCloud Drive syncs Documents, which breaks signing
# and the virtualenv); dist/ is a link to the output.
BUILD_ROOT ?= $(HOME)/Library/Caches/CR8TXXX-build
VERSION := $(shell sed -n 's/__version__ = "\(.*\)"/\1/p' src/cr8txxx/__init__.py)
DMG = $(BUILD_ROOT)/dist/CR8TXXX-$(VERSION).dmg
# The first "Developer ID Application" identity in the keychain, else ad-hoc (SIGN_ID=)
ifeq ($(origin SIGN_ID),undefined)
SIGN_ID := $(shell security find-identity -v -p codesigning 2>/dev/null \
	| sed -n 's/.*"\(Developer ID Application: .*\)"$$/\1/p' | head -1)
endif
NOTARY_PROFILE ?= FMM-notary

ffmpeg:
	packaging/build_ffmpeg.sh "$(BUILD_ROOT)"

dist: icon
	mkdir -p "$(BUILD_ROOT)/dist" "$(BUILD_ROOT)/work"
	@[ -L dist ] || ln -s "$(BUILD_ROOT)/dist" dist
	rm -rf "$(BUILD_ROOT)/dist/CR8TXXX.app" "$(BUILD_ROOT)/dist/CR8TXXX" "$(BUILD_ROOT)"/dist/CR8TXXX-*.dmg
	CR8TXXX_FFMPEG="$(BUILD_ROOT)/ffmpeg-bin" uv run --group build pyinstaller \
		packaging/cr8txxx.spec --noconfirm --distpath "$(BUILD_ROOT)/dist" \
		--workpath "$(BUILD_ROOT)/work"
	xattr -cr "$(BUILD_ROOT)/dist/CR8TXXX.app"
	@echo "Signing with $(if $(SIGN_ID),$(SIGN_ID),an ad-hoc signature)"
	packaging/sign.sh "$(BUILD_ROOT)/dist/CR8TXXX.app" "$(SIGN_ID)"
	packaging/make_dmg.sh "$(BUILD_ROOT)/dist/CR8TXXX.app" "$(DMG)" "$(SIGN_ID)"

# Sends the DMG to Apple's notary service (needs the notarytool profile FMM uses) and
# staples the ticket, so the other Mac opens it without any warning.
notarize:
	xcrun notarytool submit "$(DMG)" --keychain-profile "$(NOTARY_PROFILE)" --wait
	xcrun stapler staple "$(DMG)"
	spctl --assess -vv --type open --context context:primary-signature "$(DMG)"

clean-dist:
	rm -rf "$(BUILD_ROOT)/dist" "$(BUILD_ROOT)/work" dist
