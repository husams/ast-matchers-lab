#pragma once

#include "astmatcher.pb.h"

namespace astmatcher::native {

// Runs all commands against one translation unit without invoking clang-query.
v1::RunReply run_match_request(const v1::RunRequest &request);

} // namespace astmatcher::native
