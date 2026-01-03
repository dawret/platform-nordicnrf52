# Copyright 2014-present PlatformIO <contact@platformio.org>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


from platformio.public import PlatformBase
import platform


class Nordicnrf52Platform(PlatformBase):

    def configure_default_packages(self, options, targets):
        board = options.get("board")

        if board:
            if self.board_config(board).get("build.bsp.name", "nrf5") == "adafruit":
                self.packages["tool-adafruit-nrfutil"]["optional"] = False

        return super().configure_default_packages(options, targets)

    def is_embedded(self):
        return True
