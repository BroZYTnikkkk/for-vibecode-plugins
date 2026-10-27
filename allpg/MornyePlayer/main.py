# SPDX-License-Identifier: LGPL-3.0-only
#
# Mornye Player for exteraGram.
# Copyright 2026 BroNik (@BroZYTnikkkk).
#
# Based on Mornye by zarzet (https://github.com/mornyeapp/Mornye),
# Copyright 2026 zarzet, licensed under LGPL-3.0-only. The AutoMix beat
# detector, mix planner and equal-power envelope, the equalizer presets and
# tone formulas, and the ReplayGain volume rule are Python ports of
# lib/services/automix_analysis.dart, lib/models/automix_options.dart,
# lib/models/equalizer_settings.dart and lib/services/playback_normalization.dart.
# Search and downloads run Mornye's own JavaScript extensions (.sflx from
# Mornye extension repositories): assets/prelude.js and assets/provider.js are
# copied unchanged from rust_backend/crates/extensions/src, and the host
# functions, signed sessions, package checks and download planner are Python
# ports of that crate (host*.rs, signed_session/*, package.rs, manager/*,
# backend/downloads.rs).
# This project is distributed under the same license: GNU LGPL v3.0 only,
# see https://www.gnu.org/licenses/lgpl-3.0.html

from .mornye.plugin import MornyePlayerPlugin

__all__ = ["MornyePlayerPlugin"]
