from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room, leave_room
import json
import threading
import time
from datetime import datetime
import uuid
import random
import json
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'
socketio = SocketIO(app, cors_allowed_origins="*", logger=True, engineio_logger=True)

# 全局遊戲狀態存儲
games = {}  # game_id: GameState
players = {}  # session_id: player_info
timer_thread = None  # 計時器執行緒

class GameState:
    def __init__(self, game_id, host_player_id):
        self.game_id = game_id
        self.host_player_id = host_player_id
        self.players = {}  # player_id: player_data
        self.current_quarter = 1
        self.quarter_start_time = None
        self.quarter_duration = 30.0  # 30秒一季
        self.is_paused = False
        self.game_started = False
        self.game_log = []
        self.global_oil_price = 80.0  # 全球石油價格基準
        self.events_triggered = []  # 新增：記錄已觸發的事件
        self.event_config = self.load_events_config()  # 新增：載入事件配置
        self.event_probabilities = {
            'global': 0.5,  # 全球事件機率（每季40%）
            'country': 0.6  # 國家事件機率（每季30%）
        }
        
    def add_player(self, player_id, player_name, country_code):
        """添加玩家到遊戲"""
        print(f"添加玩家: {player_name} ({country_code})")
        self.players[player_id] = {
            'id': player_id,
            'name': player_name,
            'country_code': country_code,
            'country_name': COUNTRY_CONFIGS[country_code]['name'],
            'country_flag': COUNTRY_CONFIGS[country_code]['flag'],
            'country_data': self._initialize_country_data(country_code),
            'connected': True,
            'last_action_time': time.time()
        }
        
    def _initialize_country_data(self, country_code):
        """初始化國家數據"""
        config = COUNTRY_CONFIGS[country_code]
        data = config['starting_values'].copy()
        data.update({
            'skill_cooldown': 0,
            
            # 統一的政策冷卻時間（秒）- 改為統一10秒
            'policy_cooldowns': {
                'global_policy_cooldown': 0,  # 全局政策冷卻
                'active_skill': 0  # 主動技能冷卻（以季度計算）
            },
            
            # 政策狀態
            'gov_spending_level': 0,
            'qe_level': 0,
            'emergency_used': False,
            'emergency_confidence_used': False,
            'cash_distribution_used': False,
            'cash_distribution_cooldown': 0,
            
            # 經濟趨勢變數
            'gdp_trend': 0,
            'inflation_trend': 0,
            'unemployment_trend': 0,
            'confidence_trend': 0,
            'stock_index_trend': 0,
            
            # 股價指數特殊狀態
            'fed_put_active': False,
            'bubble_risk_level': 0,
            'panic_mode': False,
            
            # 國家特殊狀態
            'taiwan_bet_target': None,          # 台灣賭注目標國家
            'taiwan_bet_quarters_left': 0,      # 台灣賭注剩餘季度
            'brazil_anticorruption_used': False, # 巴西反貪腐是否使用過
            'saudi_transformation_level': 0,    # 沙烏地產業轉型等級
            'saudi_oil_dependency': 1.0,        # 沙烏地石油依賴度 (1.0=完全依賴, 0.0=完全獨立)
            'usa_trade_war_used': False,        # 美國貿易戰爭是否使用過
            'china_mass_mobilization_used': False, # 中國人多好辦事是否使用過
            'japan_aging_solution_used': False, # 日本老齡就業解決方案是否使用過
            
            'history': {
                'quarters': [1],
                'gdp_growth': [data['gdp_growth']],
                'inflation': [data['inflation']],
                'unemployment': [data['unemployment']],
                'confidence': [data['confidence']],
                'stock_index': [data['stock_index']]
            }
        })
        return data
    
    def start_game(self):
        """開始遊戲"""
        self.game_started = True
        self.quarter_start_time = time.time()
        self.add_log("🎮 遊戲開始！所有央行行長就位")
        print(f"遊戲 {self.game_id} 開始，計時器啟動")
        
    def get_quarter_progress(self):
        """獲取當前季度進度"""
        if not self.quarter_start_time or self.is_paused:
            return 0.0
        
        elapsed = time.time() - self.quarter_start_time
        progress = min(elapsed / self.quarter_duration, 1.0)
        return progress
        
    def get_remaining_time(self):
        """獲取剩餘時間"""
        if not self.quarter_start_time or self.is_paused:
            return self.quarter_duration
        
        elapsed = time.time() - self.quarter_start_time
        remaining = max(0, self.quarter_duration - elapsed)
        return remaining
        
    def load_events_config(self):
        """從 JSON 檔案載入事件配置"""
        try:
            config_path = os.path.join(os.path.dirname(__file__), 'events_config.json')
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                print(f"✅ 事件配置載入成功，包含 {len(config.get('globalEvents', {}).get('good', []))} 個全球好事件")
                return config
        except FileNotFoundError:
            print("⚠️ events_config.json 檔案未找到，使用預設事件")
            return self.get_default_events()
        except json.JSONDecodeError as e:
            print(f"⚠️ events_config.json 格式錯誤: {e}，使用預設事件")
            return self.get_default_events()
    
    def get_default_events(self):
        """預設事件配置（當 JSON 檔案載入失敗時使用）"""
        return {
            "globalEvents": {
                "good": [
                    {
                        "name": "全球經濟復甦",
                        "description": "國際經濟展現強勁復甦動能",
                        "effects": {"gdp": 1.0, "confidence": 10}
                    }
                ],
                "bad": [
                    {
                        "name": "國際貿易衝突",
                        "description": "主要經濟體貿易摩擦加劇",
                        "effects": {"gdp": -1.0, "confidence": -10}
                    }
                ]
            },
            "countryEvents": {}
        }
    
    def trigger_random_events(self):
        """使用配置檔案觸發隨機事件"""
        events = []
        
        # 全球事件檢查
        if random.random() < self.event_probabilities['global']:
            event = self.generate_global_event_from_config()
            if event:
                events.append(event)
                self.apply_global_event(event)
                print(f"🌍 觸發全球事件: {event['name']}")
        
        # 國家事件檢查
        for player_id, player in self.players.items():
            if random.random() < self.event_probabilities['country']:
                event = self.generate_country_event_from_config(player)
                if event:
                    events.append(event)
                    self.apply_country_event(event, player)
                    print(f"🏳️ 觸發國家事件: {event['country']} - {event['name']}")
        
        # 🔥 重要：必須回傳列表，即使是空列表
        print(f"📊 總共生成 {len(events)} 個事件")
        return events  # 絕對不能回傳 True 或其他布林值
    
    def generate_global_event_from_config(self):
        """從配置檔案生成全球事件"""
        try:
            is_good_news = random.random() < 0.5
            event_type = "good" if is_good_news else "bad"
            events_pool = self.event_config["globalEvents"][event_type]
            
            if not events_pool:
                return None
                
            selected_event = random.choice(events_pool)
            
            return {
                'type': 'global',
                'category': event_type,
                'name': selected_event['name'],
                'description': selected_event['description'],
                'effects': selected_event['effects'],
                'season': self.current_quarter
            }
        except (KeyError, IndexError) as e:
            print(f"❌ 生成全球事件時發生錯誤: {e}")
            return None
    
    def generate_country_event_from_config(self, player):
        """從配置檔案生成國家事件"""
        try:
            country_name = self.get_country_name_chinese(player['country_code'])
            country_config = self.event_config["countryEvents"].get(country_name)
            
            if not country_config:
                print(f"⚠️ 國家 {country_name} 沒有事件配置")
                return None
            
            good_news_ratio = country_config.get("goodNewsRatio", 0.5)
            is_good_news = random.random() < good_news_ratio
            event_type = "good" if is_good_news else "bad"
            
            events_pool = country_config["events"][event_type]
            if not events_pool:
                return None
                
            selected_event = random.choice(events_pool)
            
            return {
                'type': 'country',
                'country': country_name,
                'category': event_type,
                'name': selected_event['name'],
                'description': selected_event['description'],
                'effects': selected_event['effects'],
                'globalEffects': selected_event.get('globalEffects'),
                'season': self.current_quarter
            }
        except (KeyError, IndexError) as e:
            print(f"❌ 生成國家事件時發生錯誤: {e}")
            return None
    
    def get_country_name_chinese(self, country_code):
        """將國家代碼轉換為中文名稱"""
        mapping = {
            'USA': '美國',
            'CHN': '中國', 
            'JPN': '日本',
            'TWN': '台灣',
            'SAU': '沙烏地阿拉伯',
            'BRA': '巴西'
        }
        return mapping.get(country_code, country_code)
    
    def apply_global_event(self, event):
        """應用全球事件效果"""
        for player_id, player in self.players.items():
            self.apply_event_effects(player['country_data'], event['effects'])
        
        self.add_log(f"🌍 {event['name']}: {event['description']}")
        self.events_triggered.append(event)
    
    def apply_country_event(self, event, target_player):
        """應用國家事件效果"""
        self.apply_event_effects(target_player['country_data'], event['effects'])
        
        # 處理全球影響
        if event.get('globalEffects'):
            for player_id, player in self.players.items():
                if player['id'] != target_player['id']:
                    self.apply_event_effects(player['country_data'], event['globalEffects'])
        
        self.add_log(f"🏳️ {event['country']} - {event['name']}: {event['description']}")
        self.events_triggered.append(event)
    
    def apply_event_effects(self, country_data, effects):
        """應用事件效果到國家數據"""
        for effect_type, value in effects.items():
            if effect_type == 'gdp':
                country_data['gdp_trend'] += value
            elif effect_type == 'confidence':
                country_data['confidence'] = max(0, min(100, country_data['confidence'] + value))
            elif effect_type == 'inflation':
                country_data['inflation_trend'] += value
            elif effect_type == 'unemployment':
                country_data['unemployment_trend'] += value
            elif effect_type == 'deficit':
                country_data['fiscal_deficit'] += value
            elif effect_type == 'stock_index':
                country_data['stock_index_trend'] += value

    def advance_quarter(self):
        """推進到下一季度"""
        self.current_quarter += 1
        self.quarter_start_time = time.time()
        
        # 更新全球石油價格（隨機波動）
        self.update_global_oil_price()
        
        # 🔥 關鍵修正：確保正確呼叫和回傳事件
        triggered_events = self.trigger_random_events()  # 這必須回傳列表
        print(f"🎯 觸發事件數量: {len(triggered_events) if triggered_events else 0}")
        print(f"🎯 事件內容: {triggered_events}")

        # 🆕 檢查股市泡沫風險
        bubble_events = self.check_global_bubble_risk()
        if bubble_events:
            print(f"💥 股市泡沫破裂事件: {len(bubble_events)} 個")
            # 將泡沫事件加入觸發事件列表
            if triggered_events is None:
                triggered_events = []
            triggered_events.extend(bubble_events)

        # 確保回傳的是列表
        if triggered_events is None:
            triggered_events = []
        
        # 更新所有玩家的經濟指標
        for player_id, player in self.players.items():
            self._update_player_economics(player)
            
        # 執行被動技能
        self.update_passive_skills()
            
        self.add_log(f"📅 進入第{self.current_quarter}季")
        
        # 🔥 重要：確保回傳事件列表而不是布林值
        return triggered_events  # 這裡不能回傳 True
        
    def update_global_oil_price(self):
        """更新全球石油價格"""
        # 基礎隨機波動 ±5%
        base_change = random.uniform(-0.05, 0.05)
        self.global_oil_price *= (1 + base_change)
        
        # 限制在合理範圍內 ($30-$150)
        self.global_oil_price = max(30, min(150, self.global_oil_price))
        
    def update_passive_skills(self):
        """更新被動技能"""
        for player_id, player in self.players.items():
            country_code = player['country_code']
            data = player['country_data']
            
            if country_code == 'USA':
                # 【原有邏輯】美國聯準會保護機制
                #if data['stock_index'] < 80:
                #    data['fed_put_active'] = True
                #    data['stock_index_trend'] += 2.0
                #    self.add_log(f"{player['name']}: 聯準會保護機制啟動！股市獲得強力支撐")
                #else:
                #    data['fed_put_active'] = False
                    
                # 【原有邏輯】泡沫風險累積
                #if data['stock_index'] > 120:
                #    data['bubble_risk_level'] += 1
                #    if data['bubble_risk_level'] >= 3:
                #        data['stock_index'] *= 0.85
                #        data['bubble_risk_level'] = 0
                #        self.add_log(f"{player['name']}: 股市泡沫破裂！指數大幅下跌")
                
                # 【新增】美國通膨外溢被動技能
                self.update_usa_passive(data)
                        
            elif country_code == 'CHN':
                # 【原有邏輯】中國國有經濟穩定性
                #if data['gdp_growth'] < 2.0:
                #    data['gdp_trend'] += 0.5
                #    self.add_log(f"{player['name']}: 國有經濟發揮穩定器作用")
                
                # 【新增】中國商業間諜被動技能
                self.update_china_passive(data, player)
                    
            elif country_code == 'JPN':
                # 【原有邏輯】日本通縮螺旋
                if data['inflation'] < 0:
                    data['confidence_trend'] -= 0.3
                    data['gdp_trend'] -= 0.2
                
                # 【新增】日本精密製造被動技能
                self.update_japan_passive(data)
                    

            elif country_code == 'TWN':
                # 【改良版】台灣的靈活應變 - 高風險高報酬版本
                if data.get('taiwan_bet_target') and data.get('taiwan_bet_quarters_left', 0) > 0:
                    target_country = data['taiwan_bet_target']
                    # 找到目標國家
                    for target_player in self.players.values():
                        if target_player['country_code'] == target_country:
                            target_data = target_player['country_data']
                            
                            # 【新增】根據目標國家表現決定台灣的收益/損失
                            target_gdp = target_data['gdp_growth']
                            
                            if target_gdp > 2.0:
                                # 🎯 賭對了！獲得更高的收益（原本 0.8 → 1.2）
                                data['gdp_trend'] += 1.2
                                data['confidence_trend'] += 0.8
                                data['stock_index_trend'] += 2.0  # 新增股市收益
                                self.add_log(f"{player['name']}: 🎉 成功搭上{target_player['name']}的順風車！獲得豐厚收益")
                                
                            elif target_gdp < 1.0:
                                # 💥 賭錯了！承受相應的損失
                                data['gdp_trend'] -= 1.0
                                data['confidence_trend'] -= 0.6
                                data['stock_index_trend'] -= 1.5
                                data['unemployment_trend'] += 0.3  # 新增失業率惡化
                                self.add_log(f"{player['name']}: 💔 押錯寶了！{target_player['name']}表現不佳，台灣經濟受拖累")
                                
                            else:
                                # 🤷‍♂️ 目標國家表現平庸（1.0% ≤ GDP ≤ 3.0%），小幅收益
                                data['gdp_trend'] += 0.3
                                data['confidence_trend'] += 0.2
                                self.add_log(f"{player['name']}: 😐 {target_player['name']}表現平平，台灣獲得少量收益")
                            
                            break
                            
                    data['taiwan_bet_quarters_left'] -= 1
                    if data['taiwan_bet_quarters_left'] <= 0:
                        data['taiwan_bet_target'] = None
                        # 【新增】技能結束後設置冷卻
                        data['policy_cooldowns']['active_skill'] = 4  # 台灣技能結束後冷卻4季
                        self.add_log(f"{player['name']}: 夾縫求生戰略結束，進入冷卻期")
                
                # 【保留】台灣外貿依賴被動技能
                self.update_taiwan_passive(data)
                        
            elif country_code == 'BRA':
                # 【新增】巴西大宗商品被動技能
                self.update_brazil_passive(data)
                        
            elif country_code == 'SAU':
                # 【修改】原有的沙烏地石油依賴邏輯移到新函數中
                # 原有代碼：
                # oil_impact = (self.global_oil_price - 80) / 80 * data['saudi_oil_dependency']
                # data['gdp_trend'] += oil_impact * 0.5
                # data['fiscal_deficit'] -= oil_impact * 2.0
                
                # 【新增】更完整的沙烏地被動技能
                self.update_saudi_passive(data)
        
        # 【新增】更新油價對各國的影響
        self.update_oil_price_effects()
        
        # 【新增】檢查油價相關事件
        self.check_oil_price_events()
    
    def update_usa_passive(self, data):
        """美國被動技能：通膨外溢"""
        # 計算美國通膨增量
        baseline_inflation = COUNTRY_CONFIGS['USA']['starting_values']['inflation']
        current_inflation = data['inflation']
        inflation_increase = max(0, current_inflation - baseline_inflation)
        
        if inflation_increase > 0:
            # 美國通膨乘以0.8
            data['inflation'] = baseline_inflation + (inflation_increase * 0.8)
            
            # 剩餘的0.2分散到其他國家
            spillover_effect = inflation_increase * 0.2
            other_players = [p for p in self.players.values() if p['country_code'] != 'USA']
            
            if other_players:
                spillover_per_country = spillover_effect / len(other_players)
                for player in other_players:
                    player['country_data']['inflation'] += spillover_per_country
                    
                if spillover_effect > 0.1:
                    self.add_log(f"🇺🇸 美國通膨外溢：向全球傳導{spillover_effect:.1f}%通膨壓力")

    def update_china_passive(self, data, china_player):
        """中國被動技能：商業間諜"""
        # 20%機率觸發
        if random.random() < 0.2:
            # 找到上一季GDP成長最高的國家
            best_gdp_country = None
            best_gdp_growth = -float('inf')
            
            for player in self.players.values():
                if player['country_code'] != 'CHN':
                    other_gdp = player['country_data']['gdp_growth']
                    if other_gdp > best_gdp_growth:
                        best_gdp_growth = other_gdp
                        best_gdp_country = player
                        
            if best_gdp_country and best_gdp_growth > 0:
                # 獲得30%經濟成果
                stolen_benefit = best_gdp_growth * 0.3
                data['gdp_growth'] += stolen_benefit
                
                self.add_log(f"🇨🇳 中國商業間諜：從{best_gdp_country['country_name']}獲得{stolen_benefit:.1f}% GDP成長")

    def update_japan_passive(self, data):
        """日本被動技能：精密製造"""
        # GDP成長小幅增加
        data['gdp_growth'] += 0.15
        data['confidence'] += 1
        data['stock_index'] += 0.1
        
        # 每10季顯示一次訊息
        if self.current_quarter % 10 == 0:
            self.add_log("🇯🇵 日本精密製造：持續技術進步，經濟穩定成長")

    def update_taiwan_passive(self, data):
        """台灣被動技能：依靠外貿的小島"""
        # 計算所有其他玩家的平均GDP和通膨
        other_players = [p for p in self.players.values() if p['country_code'] != 'TWN']
        if not other_players:
            return
            
        avg_gdp = sum(p['country_data']['gdp_growth'] for p in other_players) / len(other_players)
        avg_inflation = sum(p['country_data']['inflation'] for p in other_players) / len(other_players)
        
        # 台灣基準值（用於計算變化）
        taiwan_baseline_gdp = COUNTRY_CONFIGS['TWN']['starting_values']['gdp_growth']
        taiwan_baseline_inflation = COUNTRY_CONFIGS['TWN']['starting_values']['inflation']
        
        # 計算平均變化並影響台灣（0.5倍係數）
        gdp_change = (avg_gdp - taiwan_baseline_gdp) * 0.5
        inflation_change = (avg_inflation - taiwan_baseline_inflation) * 0.5
        
        data['gdp_growth'] += gdp_change * 0.1  # 每季度小幅調整
        data['inflation'] += inflation_change * 0.1

    def update_brazil_passive(self, data):
        """巴西被動技能：大宗商品出口國"""
        # 60%機會+1.5%，40%機會-1.2%
        if random.random() < 0.6:
            data['gdp_growth'] += 1.5
            if random.random() < 0.1:  # 10%機率顯示訊息
                self.add_log("🇧🇷 巴西：大宗商品價格上漲，經濟受益")
        else:
            data['gdp_growth'] -= 1.2
            if random.random() < 0.1:  # 10%機率顯示訊息
                self.add_log("🇧🇷 巴西：大宗商品價格下跌，經濟受損")

    def update_saudi_passive(self, data):
        """沙烏地被動技能：石油價格依賴（考慮轉型程度）"""
        oil_price_change = (self.global_oil_price - 80) / 80
        
        # 轉型程度影響敏感度
        transformation_level = data.get('saudi_transformation_level', 0)
        base_dependency = 1.0
        
        # 每次轉型降低25%依賴度
        current_dependency = base_dependency - (transformation_level * 0.25)
        data['saudi_oil_dependency'] = max(0.25, current_dependency)  # 最低25%依賴
        
        # 計算影響（依賴度越低影響越小）
        impact = oil_price_change * data['saudi_oil_dependency']
        
        # 【修改】使用與原有邏輯相同的影響係數，但加強
        data['gdp_trend'] += impact * 0.5  # 保持原有係數
        data['fiscal_deficit'] -= impact * 2.0  # 保持原有係數
        
        # 【新增】額外的影響
        data['confidence'] += impact * 10
        
        # 轉型帶來的穩定性收益
        if transformation_level > 0:
            stability_bonus = transformation_level * 0.1
            data['gdp_growth'] += stability_bonus
            data['confidence'] += stability_bonus * 5
        
        # 記錄顯著影響
        if abs(impact) > 0.1:
            dependency_desc = f"依賴度{data['saudi_oil_dependency']*100:.0f}%"
            direction = "受益" if impact > 0 else "受損"
            effect_size = "顯著" if abs(impact) > 0.3 else "輕微"
            self.add_log(f"🇸🇦 沙烏地：油價變動{effect_size}{direction}經濟（{dependency_desc}）")

    def update_oil_price_effects(self):
        """更新油價對各國的影響"""
        oil_change_rate = (self.global_oil_price - 80) / 80  # 相對於$80基準的變化率
        
        # 只有在油價變化顯著時才應用影響
        if abs(oil_change_rate) < 0.05:  # 變化小於5%時忽略
            return
        
        for player_id, player in self.players.items():
            country_code = player['country_code']
            data = player['country_data']
            
            if country_code == 'SAU':
                # 沙烏地：在 update_saudi_passive 中處理
                continue
                
            elif country_code == 'USA':
                # 美國：混合影響（石油生產vs消費）
                if oil_change_rate > 0:
                    data['gdp_trend'] += oil_change_rate * 0.3  # 能源產業受益
                    data['inflation_trend'] += oil_change_rate * 0.4  # 通膨壓力
                else:
                    data['gdp_trend'] += oil_change_rate * 0.2  # 消費者受益
                    data['inflation_trend'] += oil_change_rate * 0.3
                    
            elif country_code == 'CHN':
                # 中國：石油進口國，油價上漲不利
                data['gdp_trend'] -= oil_change_rate * 0.5  # 製造業成本
                data['inflation_trend'] += oil_change_rate * 0.3
                data['stock_index_trend'] -= oil_change_rate * 2.0
                
            elif country_code == 'JPN':
                # 日本：高度依賴石油進口
                data['gdp_trend'] -= oil_change_rate * 0.6
                data['inflation_trend'] += oil_change_rate * 0.4
                data['confidence_trend'] -= oil_change_rate * 5
                
            elif country_code == 'TWN':
                # 台灣：出口導向，油價影響製造成本
                data['gdp_trend'] -= oil_change_rate * 0.4
                data['inflation_trend'] += oil_change_rate * 0.3
                
            elif country_code == 'BRA':
                # 巴西：石油生產國但也是消費國
                data['gdp_trend'] += oil_change_rate * 0.2
                data['inflation_trend'] += oil_change_rate * 0.5  # 通膨敏感

    def check_oil_price_events(self):
        """檢查油價相關事件"""
        if self.global_oil_price > 120:
            if random.random() < 0.1:  # 10%機率
                self.add_log("⚠️ 油價高漲引發全球通膨擔憂，央行面臨政策兩難")
                # 所有國家通膨壓力增加
                for player in self.players.values():
                    if player['country_code'] != 'SAU':
                        player['country_data']['inflation_trend'] += 0.3
                        
        elif self.global_oil_price < 50:
            if random.random() < 0.1:  # 10%機率
                self.add_log("📉 油價暴跌衝擊能源國經濟，通縮風險升溫")
                # 石油出口國受衝擊
                for player in self.players.values():
                    if player['country_code'] in ['SAU', 'BRA']:
                        player['country_data']['gdp_trend'] -= 0.5
                        player['country_data']['confidence_trend'] -= 5
                        
        # 極端油價警報
        if self.global_oil_price > 140:
            if random.random() < 0.05:  # 5%機率
                self.add_log("🚨 油價飆破$140！全球經濟衰退風險急升")
                for player in self.players.values():
                    player['country_data']['confidence_trend'] -= 10
                    
        elif self.global_oil_price < 35:
            if random.random() < 0.05:  # 5%機率
                self.add_log("💥 油價崩盤至$35以下！能源企業面臨破產潮")
                for player in self.players.values():
                    if player['country_code'] in ['SAU', 'BRA']:
                        player['country_data']['stock_index_trend'] -= 5

    def add_log(self, message):
        """添加遊戲日誌"""
        self.game_log.append({
            'quarter': self.current_quarter,
            'message': message,
            'timestamp': time.time()
        })

    def check_global_bubble_risk(self):
        """檢查全球股市泡沫風險"""
        triggered_bubbles = []
        
        for player_id, player in self.players.items():
            country_data = player['country_data']
            
            # 計算泡沫風險機率 - 基於報酬率而非絕對值
            stock_index = country_data['stock_index']
            return_rate = stock_index - 100  # 計算報酬率（如 125 -> +25%）
            
            # 🔧 基於報酬率的泡沫風險：報酬率超過+10%時開始有風險
            bubble_probability = min(0.6, max(0.0, (return_rate - 10) * 0.03))  # +10%以上開始有風險
            
            # 🆕 添加除錯訊息 - 顯示報酬率
            if return_rate > 10:
                print(f"🎯 {player['country_name']} 股價報酬率: +{return_rate:.1f}%, 泡沫機率: {bubble_probability*100:.1f}%")
            
            # 檢查是否觸發泡沫破裂
            if random.random() < bubble_probability:
                print(f"💥 觸發泡沫破裂！{player['country_name']} 報酬率: +{return_rate:.1f}%")
                bubble_event = self.trigger_bubble_burst(player)
                if bubble_event:
                    triggered_bubbles.append(bubble_event)
                    
        return triggered_bubbles

    def trigger_bubble_burst(self, player):
        """觸發股市泡沫破裂"""
        country_data = player['country_data']
        country_name = player['country_name']
        
        # 記錄破裂前的指數和報酬率
        original_index = country_data['stock_index']
        original_return = original_index - 100
        print(f"💥 {country_name} 泡沫破裂前報酬率: +{original_return:.1f}% (指數: {original_index:.1f})")
        
        # 🔧 計算泡沫破裂程度 - 基於報酬率
        return_rate = original_index - 100
        # 報酬率越高，額外跌幅越大（最多額外30%跌幅）
        bubble_severity = min(0.30, max(0, return_rate / 100))  # +20%報酬率 = 20%額外跌幅
        
        # 🔧 基礎跌幅20% + 泡沫嚴重度（確保明顯的跌幅）
        total_crash = 0.20 + bubble_severity
        
        print(f"💥 {country_name} 計算跌幅: 基礎20% + 額外{bubble_severity*100:.1f}% = 總計{total_crash*100:.1f}%")
        
        # 🔧 立即影響股市 - 確保明顯跌幅
        country_data['stock_index'] *= (1 - total_crash)
        new_index = country_data['stock_index']
        new_return = new_index - 100
        
        print(f"💥 {country_name} 泡沫破裂後報酬率: {new_return:+.1f}% (指數: {new_index:.1f})")
        print(f"💥 {country_name} 實際跌幅: {((original_index-new_index)/original_index)*100:.1f}%")
        
        # 對經濟的立即衝擊（放大影響）
        gdp_impact = -total_crash * 10  # 增強GDP影響
        confidence_impact = -total_crash * 150  # 增強信心影響
        unemployment_impact = total_crash * 5  # 增強失業影響
        
        country_data['gdp_trend'] += gdp_impact
        country_data['confidence'] = max(0, country_data['confidence'] + confidence_impact)
        country_data['unemployment_trend'] += unemployment_impact
        
        # 記錄日誌 - 顯示報酬率變化
        crash_percentage = total_crash * 100
        self.add_log(f"💥 {country_name}股市泡沫破裂！報酬率從+{original_return:.1f}%暴跌至{new_return:+.1f}%，經濟陷入衰退")
        
        # 創建泡沫破裂事件
        bubble_event = {
            'type': 'country',
            'country': country_name,
            'category': 'bad',
            'name': f'{country_name}股市泡沫破裂',
            'description': f'股市報酬率從+{original_return:.1f}%暴跌至{new_return:+.1f}%，跌幅{crash_percentage:.1f}%，金融體系受到重創',
            'effects': {
                'stock_index': -crash_percentage,
                'gdp': gdp_impact,
                'confidence': confidence_impact,
                'unemployment': unemployment_impact
            },
            'season': self.current_quarter,
            'bubble_severity': crash_percentage,
            'original_return': original_return,
            'new_return': new_return
        }
        
        return bubble_event
        
    def _update_player_economics(self, player):
        """更新玩家經濟指標（季度結束時）"""
        data = player['country_data']
        
        # 基礎經濟變化
        data['gdp_growth'] += random.uniform(-0.3, 0.3)
        data['inflation'] += random.uniform(-0.2, 0.2)
        data['unemployment'] += random.uniform(-0.3, 0.3)
        data['confidence'] += random.uniform(-2, 2)
        data['stock_index'] += random.uniform(-3, 3)
        
        # 應用趨勢
        data['gdp_growth'] += data.get('gdp_trend', 0)
        data['inflation'] += data.get('inflation_trend', 0)
        data['unemployment'] += data.get('unemployment_trend', 0)
        data['confidence'] += data.get('confidence_trend', 0)
        data['stock_index'] += data.get('stock_index_trend', 0)
        
        # 限制範圍
        data['gdp_growth'] = max(-8, min(12, data['gdp_growth']))
        data['inflation'] = max(-3, min(8, data['inflation']))
        data['unemployment'] = max(1, min(25, data['unemployment']))
        data['confidence'] = max(0, min(100, data['confidence']))
        data['stock_index'] = max(20, min(200, data['stock_index']))
        
        # 重置趨勢（部分衰減）
        data['gdp_trend'] *= 0.7
        data['inflation_trend'] *= 0.7
        data['unemployment_trend'] *= 0.7
        data['confidence_trend'] *= 0.7
        data['stock_index_trend'] *= 0.7
        
        # 更新歷史記錄
        history = data['history']
        history['quarters'].append(self.current_quarter)
        history['gdp_growth'].append(data['gdp_growth'])
        history['inflation'].append(data['inflation'])
        history['unemployment'].append(data['unemployment'])
        history['confidence'].append(data['confidence'])
        history['stock_index'].append(data['stock_index'])
        
        # 技能冷卻減少
        if data['policy_cooldowns']['active_skill'] > 0:
            data['policy_cooldowns']['active_skill'] -= 1
            
        if data.get('cash_distribution_cooldown', 0) > 0:
            data['cash_distribution_cooldown'] -= 1


# 國家配置
COUNTRY_CONFIGS = {
    'USA': {
        'name': '美國',
        'flag': '🇺🇸',
        'starting_values': {
            'gdp_growth': 2.8,
            'inflation': 2.1,
            'unemployment': 4.2,
            'confidence': 65,
            'stock_index': 102.5,  # 初始報酬率 +2.5%
            'interest_rate': 2.5,
            'reserve_ratio': 10.0,
            'fiscal_deficit': 3.2
        }
    },
    'CHN': {
        'name': '中國',
        'flag': '🇨🇳',
        'starting_values': {
            'gdp_growth': 6.2,
            'inflation': 1.8,
            'unemployment': 5.1,
            'confidence': 72,
            'stock_index': 103.8,  # 初始報酬率 +3.8%（高成長預期）
            'interest_rate': 3.8,
            'reserve_ratio': 12.0,
            'fiscal_deficit': 2.8
        }
    },
    'JPN': {
        'name': '日本',
        'flag': '🇯🇵',
        'starting_values': {
            'gdp_growth': 1.2,
            'inflation': 0.3,
            'unemployment': 2.8,
            'confidence': 58,
            'stock_index': 98.5,   # 初始報酬率 -1.5%（通縮擔憂）
            'interest_rate': -0.1,
            'reserve_ratio': 8.0,
            'fiscal_deficit': 7.1
        }
    },
    'EUR': {
        'name': '歐盟',
        'flag': '🇪🇺',
        'starting_values': {
            'gdp_growth': 1.8,
            'inflation': 1.2,
            'unemployment': 6.8,
            'confidence': 62,
            'stock_index': 101.2,  # 初始報酬率 +1.2%（溫和成長）
            'interest_rate': 0.0,
            'reserve_ratio': 9.5,
            'fiscal_deficit': 2.1
        }
    },
    'BRA': {
        'name': '巴西',
        'flag': '🇧🇷',
        'starting_values': {
            'gdp_growth': 2.3,
            'inflation': 4.2,
            'unemployment': 11.8,
            'confidence': 45,
            'stock_index': 97.2,   # 初始報酬率 -2.8%（政治不穩定）
            'interest_rate': 6.5,
            'reserve_ratio': 15.0,
            'fiscal_deficit': 6.8
        }
    },
    'SAU': {
        'name': '沙烏地阿拉伯',
        'flag': '🇸🇦',
        'starting_values': {
            'gdp_growth': 3.2,
            'inflation': 2.8,
            'unemployment': 6.2,
            'confidence': 68,
            'stock_index': 104.5,  # 初始報酬率 +4.5%（油價利好）
            'interest_rate': 2.8,
            'reserve_ratio': 11.0,
            'fiscal_deficit': -2.1
        }
    },
    'TWN': {
        'name': '台灣',
        'flag': '🇹🇼',
        'starting_values': {
            'gdp_growth': 2.8,
            'inflation': 1.6,
            'unemployment': 3.8,
            'confidence': 72,
            'stock_index': 102.1,  # 初始報酬率 +2.1%（科技優勢）
            'interest_rate': 1.4,
            'reserve_ratio': 13.0,
            'fiscal_deficit': 1.2
        }
    }
}

def start_timer_thread():
    """啟動計時器執行緒"""
    global timer_thread
    if timer_thread is None or not timer_thread.is_alive():
        timer_thread = threading.Thread(target=game_timer, daemon=True)
        timer_thread.start()
        print("遊戲計時器執行緒已啟動")

def game_timer():
    """遊戲計時器（背景執行緒）"""
    print("遊戲計時器開始運行")
    while True:
        try:
            time.sleep(0.5)
            
            for game_id, game in list(games.items()):
                if not game.game_started or game.is_paused:
                    continue
                    
                # 實時更新經濟指標
                for player_id, player in game.players.items():
                    update_realtime_economics(player['country_data'])
                    
                # 檢查是否需要推進季度
                if game.get_quarter_progress() >= 1.0:
                    triggered_events = game.advance_quarter()
                    
                    print(f"📊 game_timer 收到事件: {type(triggered_events)}, 內容: {triggered_events}")
                    
                    socketio.emit('quarter_advanced', {
                        'quarter': game.current_quarter,
                        'players': list(game.players.values()),
                        'game_log': game.game_log[-3:],
                        'full_game_log': game.game_log,
                        'global_oil_price': game.global_oil_price,
                        'triggered_events': triggered_events  # 確保這是列表
                    }, room=game_id)
                
                # 更新政策冷卻時間
                current_time = time.time()
                players_data = []
                
                for player_id, player in game.players.items():
                    cooldowns = player['country_data']['policy_cooldowns']
                    cooldown_status = {}
                    
                    # 全局政策冷卻
                    global_remaining = max(0, cooldowns.get('global_policy_cooldown', 0) - current_time)
                    cooldown_status['global_policy_cooldown'] = global_remaining
                    
                    # 主動技能季度冷卻
                    cooldown_status['active_skill'] = cooldowns.get('active_skill', 0)
                    
                    players_data.append({
                        'player_id': player_id,
                        'cooldown_status': cooldown_status
                    })
                
                # 發送實時更新
                socketio.emit('realtime_update', {
                    'progress': game.get_quarter_progress(),
                    'remaining_time': game.get_remaining_time(),
                    'players_cooldowns': players_data,
                    'players': list(game.players.values()),
                    'global_oil_price': game.global_oil_price
                }, room=game_id)
                
        except Exception as e:
            print(f"計時器執行錯誤: {e}")
            continue

def update_realtime_economics(country_data):
    """實時更新經濟指標（季度內持續變化）"""
    update_rate = 0.02
    
    country_data['gdp_growth'] += country_data.get('gdp_trend', 0) * update_rate
    country_data['inflation'] += country_data.get('inflation_trend', 0) * update_rate
    country_data['unemployment'] += country_data.get('unemployment_trend', 0) * update_rate
    country_data['confidence'] += country_data.get('confidence_trend', 0) * update_rate
    country_data['stock_index'] += country_data.get('stock_index_trend', 0) * update_rate
    
    # 限制範圍
    country_data['gdp_growth'] = max(-8, min(12, country_data['gdp_growth']))
    country_data['inflation'] = max(-3, min(8, country_data['inflation']))
    country_data['unemployment'] = max(1, min(25, country_data['unemployment']))
    country_data['confidence'] = max(0, min(100, country_data['confidence']))
    country_data['stock_index'] = max(20, min(200, country_data['stock_index']))

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('connect')
def on_connect():
    player_id = str(uuid.uuid4())
    players[request.sid] = {'id': player_id}
    emit('connected', {'player_id': player_id})
    print(f"玩家連接: {request.sid}, ID: {player_id}")
    
    # 確保計時器執行緒運行
    start_timer_thread()

@socketio.on('disconnect')
def on_disconnect():
    if request.sid in players:
        player_info = players[request.sid]
        print(f"玩家斷線: {request.sid}")
        
        if 'game_id' in player_info:
            game_id = player_info['game_id']
            if game_id in games:
                game = games[game_id]
                if player_info['id'] in game.players:
                    game.players[player_info['id']]['connected'] = False
        
        del players[request.sid]

@socketio.on('create_game')
def on_create_game(data):
    game_id = str(random.randint(1000, 9999))
    player_name = data['player_name']
    country_code = data['country_code']
    
    player_info = players[request.sid]
    player_id = player_info['id']
    
    # 創建遊戲
    game = GameState(game_id, player_id)
    game.add_player(player_id, player_name, country_code)
    games[game_id] = game
    
    # 更新玩家信息
    player_info.update({
        'game_id': game_id,
        'name': player_name,
        'country_code': country_code
    })
    
    join_room(game_id)
    
    emit('game_created', {
        'game_id': game_id,
        'player_data': game.players[player_id]
    })
    
    print(f"遊戲創建: {game_id}, 房主: {player_name} ({country_code})")

@socketio.on('join_game')
def on_join_game(data):
    game_id = data['game_id']
    player_name = data['player_name']
    country_code = data['country_code']
    
    if game_id not in games:
        emit('error', {'message': '遊戲房間不存在'})
        return
    
    game = games[game_id]
    
    # 檢查國家是否已被選擇
    for existing_player in game.players.values():
        if existing_player['country_code'] == country_code:
            emit('error', {'message': '此國家已被其他玩家選擇'})
            return
    
    player_info = players[request.sid]
    player_id = player_info['id']
    
    # 添加玩家到遊戲
    game.add_player(player_id, player_name, country_code)
    
    # 更新玩家信息
    player_info.update({
        'game_id': game_id,
        'name': player_name,
        'country_code': country_code
    })
    
    join_room(game_id)
    
    print(f"玩家加入遊戲 {game_id}")
    
    socketio.emit('player_joined', {
        'player_data': game.players[players[request.sid]['id']],
        'all_players': list(game.players.values())
    }, room=game_id)

@socketio.on('start_game')
def on_start_game():
    """開始遊戲"""
    print(f"開始遊戲請求，session: {request.sid}")
    
    if request.sid not in players:
        emit('error', {'message': '用戶未連接'})
        return
        
    player_info = players[request.sid]
    game_id = player_info['game_id']
    
    if game_id not in games:
        emit('error', {'message': '遊戲不存在'})
        return
        
    game = games[game_id]
    
    if player_info['id'] != game.host_player_id:
        emit('error', {'message': '只有房主可以開始遊戲'})
        return
    
    print(f"房主開始遊戲 {game_id}")
    game.start_game()
    socketio.emit('game_started', {}, room=game_id)

@socketio.on('policy_action')
def on_policy_action(data):
    """處理政策行動 - 統一冷卻系統"""
    print(f"政策行動: {data}")
    
    if request.sid not in players:
        return
        
    player_info = players[request.sid]
    game_id = player_info['game_id']
    
    if game_id not in games:
        return
        
    game = games[game_id]
    player = game.players[player_info['id']]
    
    action_type = data['action_type']
    cooldowns = player['country_data']['policy_cooldowns']
    current_time = time.time()
    
    # 檢查主動技能冷卻（季度冷卻）
    if action_type in ['taiwan_bet', 'brazil_anticorruption', 'saudi_transformation', 
                       'usa_trade_war', 'china_mass_mobilization', 'japan_aging_solution']:
        skill_cooldown = cooldowns.get('active_skill', 0)
        if skill_cooldown > 0:
            emit('error', {'message': f'{get_policy_name(action_type)}冷卻中，還需等待 {skill_cooldown} 季'})
            return
    else:
        # 檢查全局政策冷卻（10秒統一冷卻）
        if current_time < cooldowns.get('global_policy_cooldown', 0):
            remaining = int(cooldowns['global_policy_cooldown'] - current_time)
            emit('error', {'message': f'政策冷卻中，還需等待 {remaining} 秒才能發動下個政策'})
            return
    
    success = False
    message = ""
    
    # 處理各種政策
    if action_type == 'interest_rate':
        success, message = handle_interest_rate_change(player, data['value'])
    elif action_type == 'reserve_ratio':
        success, message = handle_reserve_ratio_change(player, data['value'])
    elif action_type == 'fiscal_policy':
        success, message = handle_fiscal_policy(player, data['policy_type'])
    elif action_type == 'quantitative_easing':
        success, message = handle_quantitative_easing(player, data['direction'])
    elif action_type == 'cash_distribution':
        success, message = handle_cash_distribution(player)
    elif action_type == 'taiwan_bet':
        success, message = handle_taiwan_bet(player, data.get('target_country'))
    elif action_type == 'brazil_anticorruption':
        success, message = handle_brazil_anticorruption(player)
    elif action_type == 'saudi_transformation':
        success, message = handle_saudi_transformation(player)
    elif action_type == 'oil_control':
        success, message = handle_oil_control(game, player, data.get('direction'))
    elif action_type == 'usa_trade_war':
        success, message = handle_usa_trade_war(game, player, data.get('target_country'))
    elif action_type == 'china_mass_mobilization':
        success, message = handle_china_mass_mobilization(player)
    elif action_type == 'japan_aging_solution':
        success, message = handle_japan_aging_solution(player)
    
    if success:
        # 設置冷卻時間
        if action_type in ['taiwan_bet', 'brazil_anticorruption', 'saudi_transformation', 
                           'usa_trade_war', 'china_mass_mobilization', 'japan_aging_solution']:
            # 主動技能冷卻在各自的處理函數中設置
            pass
        else:
            # 設置統一的10秒全局政策冷卻
            cooldowns['global_policy_cooldown'] = current_time + 10
        
        game.add_log(f"{player['name']}: {message}")
        
        socketio.emit('game_update', {
            'players': list(game.players.values()),
            'game_log': game.game_log[-5:],
            'global_oil_price': game.global_oil_price
        }, room=game_id)
    else:
        emit('error', {'message': message})

def get_policy_name(action_type):
    """獲取政策名稱"""
    names = {
        'interest_rate': '利率政策',
        'reserve_ratio': '存款準備金率',
        'fiscal_policy': '財政政策',
        'quantitative_easing': '量化寬鬆政策',
        'cash_distribution': '普發現金',
        'taiwan_bet': '夾縫中求生存',
        'brazil_anticorruption': '反貪腐行動',
        'saudi_transformation': '產業轉型',
        'oil_control': '石油產量控制',
        'usa_trade_war': '發動貿易戰爭',
        'china_mass_mobilization': '人多好辦事',
        'japan_aging_solution': '解決老齡就業問題'
    }
    return names.get(action_type, '政策')

# ===== 政策處理函數 =====

def handle_interest_rate_change(player, new_rate):
    """處理利率變化"""
    data = player['country_data']
    old_rate = data['interest_rate']
        # 【修改這裡】新的範圍驗證：-2% 到 20%
    if new_rate < -2 or new_rate > 20:
        return False, "利率超出允許範圍（-2% 到 20%）"
    
    data['interest_rate'] = new_rate
    rate_change = new_rate - old_rate
    
    # 利率影響
    if rate_change > 0:  # 升息
        data['inflation_trend'] -= rate_change * 0.8
        data['gdp_trend'] -= rate_change * 0.6
        data['stock_index_trend'] -= rate_change * 8
        data['unemployment_trend'] += rate_change * 0.4
        return True, f"升息 {rate_change:.2f}% 抑制通膨但拖累經濟成長"
    else:  # 降息
        data['inflation_trend'] -= rate_change * 0.5
        data['gdp_trend'] -= rate_change * 0.8
        data['stock_index_trend'] -= rate_change * 10
        data['unemployment_trend'] += rate_change * 0.3
        return True, f"降息 {abs(rate_change):.2f}% 刺激經濟但推高通膨"

def handle_reserve_ratio_change(player, new_ratio):
    """處理存款準備金率變化"""
    data = player['country_data']
    old_ratio = data['reserve_ratio']

        # 【修改這裡】新的範圍驗證：0% 到 30%
    if new_ratio < 0 or new_ratio > 30:
        return False, "準備金率超出允許範圍（0% 到 30%）"
    
    data['reserve_ratio'] = new_ratio
    ratio_change = new_ratio - old_ratio
    
    # 準備金率影響
    if ratio_change > 0:  # 提高準備金率
        data['inflation_trend'] -= ratio_change * 0.3
        data['gdp_trend'] -= ratio_change * 0.2
        data['stock_index_trend'] -= ratio_change * 2
        return True, f"提高準備金率 {ratio_change:.1f}% 緊縮銀根"
    else:  # 降低準備金率
        data['inflation_trend'] -= ratio_change * 0.2
        data['gdp_trend'] -= ratio_change * 0.3
        data['stock_index_trend'] -= ratio_change * 3
        return True, f"降低準備金率 {abs(ratio_change):.1f}% 釋放流動性"

def handle_fiscal_policy(player, policy_type):
    """處理財政政策"""
    data = player['country_data']
    
    if policy_type == 'increase_spending':
        if data['gov_spending_level'] >= 3:
            return False, "政府支出已達上限，財政負擔過重"
        
        data['gov_spending_level'] += 1
        data['gdp_trend'] += 1.2
        data['unemployment_trend'] -= 0.8
        data['confidence_trend'] += 3
        data['fiscal_deficit'] += 1.5
        data['inflation_trend'] += 0.4
        
        return True, "擴大政府支出刺激經濟，但財政赤字惡化"
        
    elif policy_type == 'decrease_spending':
        if data['gov_spending_level'] <= -2:
            return False, "政府支出已大幅削減，無法再進一步緊縮"
        
        data['gov_spending_level'] -= 1
        data['gdp_trend'] -= 0.8
        data['unemployment_trend'] += 0.6
        data['confidence_trend'] -= 2
        data['fiscal_deficit'] -= 1.0
        
        return True, "削減政府支出改善財政，但拖累經濟成長"

def handle_quantitative_easing(player, direction):
    """處理量化寬鬆政策"""
    data = player['country_data']
    
    if direction == 'easing':  # QE
        if data['qe_level'] >= 3:
            return False, "量化寬鬆已達極限，市場邊際效應遞減"
        
        data['qe_level'] += 1
        data['stock_index_trend'] += 8
        data['gdp_trend'] += 0.6
        data['inflation_trend'] += 0.8
        data['confidence_trend'] += 4
        
        return True, "實施量化寬鬆，資產價格上漲但通膨壓力上升"
        
    elif direction == 'tightening':  # QT
        if data['qe_level'] <= -1:
            return False, "緊縮政策已實施，無法進一步收緊"
        
        data['qe_level'] -= 1
        data['stock_index_trend'] -= 12
        data['gdp_trend'] -= 0.4
        data['inflation_trend'] -= 0.6
        data['confidence_trend'] -= 6
        
        return True, "實施量化緊縮，控制通膨但資產價格承壓"

def handle_cash_distribution(player):
    """處理普發現金"""
    data = player['country_data']
    
    if data.get('cash_distribution_cooldown', 0) > 0:
        return False, f"普發現金冷卻中，還需等待 {data['cash_distribution_cooldown']} 季"
    
    if data['confidence'] > 60:
        return False, "民眾信心較高時不需要普發現金"
    
    data['confidence'] += 25
    data['fiscal_deficit'] += 5.0
    data['gdp_trend'] += 0.5
    data['stock_index_trend'] += 1.2
    data['inflation_trend'] += 0.4
    data['cash_distribution_cooldown'] = 4
    
    return True, "實施緊急普發現金！民眾信心大增，股市因消費刺激而上漲，但通膨擔憂升溫"

# ===== 主動技能處理函數 =====

def handle_usa_trade_war(game, player, target_country):
    """處理美國主動技能：發動貿易戰爭"""
    if player['country_code'] != 'USA':
        return False, "只有美國可以發動貿易戰爭"
        
    data = player['country_data']
    
    if not target_country:
        return False, "請選擇目標國家"
    
    # 找到目標國家
    target_player = None
    for p in game.players.values():
        if p['country_code'] == target_country:
            target_player = p
            break
    
    if not target_player:
        return False, "目標國家不存在"
    
    if target_country == 'USA':
        return False, "不能對自己發動貿易戰爭"
    
    # 執行貿易戰爭
    target_data = target_player['country_data']
    
    # 對目標國家的影響（嚴重負面）
    target_data['gdp_trend'] -= 2.5
    target_data['unemployment_trend'] += 1.5
    target_data['confidence_trend'] -= 8
    target_data['stock_index_trend'] -= 15
    
    # 對美國自身的影響（35%機率反噬）
    if random.random() < 0.35:
        data['gdp_trend'] -= 1.0
        data['inflation_trend'] += 0.8
        data['confidence_trend'] -= 5
        retaliation_msg = "，但遭到強烈反制，美國經濟也受到衝擊"
    else:
        data['gdp_trend'] += 0.5
        data['confidence_trend'] += 3
        retaliation_msg = "，美國經濟因貿易保護獲益"
    
    # 設置冷卻和使用標記
    data['policy_cooldowns']['active_skill'] = 5
    
    game.add_log(f"🚨 美國對{target_player['name']}發動貿易戰爭！全球經濟震盪")
    
    return True, f"對{target_player['name']}發動貿易戰爭{retaliation_msg}"

def handle_china_mass_mobilization(player):
    """處理中國主動技能：人多好辦事"""
    if player['country_code'] != 'CHN':
        return False, "只有中國可以使用人多好辦事"
        
    data = player['country_data']
    
    # 集中力量辦大事的效果
    data['gdp_trend'] += 3.0
    data['confidence_trend'] += 10
    data['stock_index_trend'] += 12
    data['unemployment_trend'] -= 1.0
    
    # 設置使用標記和冷卻
    data['policy_cooldowns']['active_skill'] = 4
    
    return True, "集中力量辦大事！實現重大科技突破，GDP成長大幅提升，民眾信心爆棚"

def handle_japan_aging_solution(player):
    """處理日本主動技能：解決老齡就業問題"""
    if player['country_code'] != 'JPN':
        return False, "只有日本可以使用改善老人就業問題"
        
    data = player['country_data']
    
    # 透過數位化培訓提升高齡勞動參與率
    data['unemployment_trend'] -= 1.5
    data['gdp_trend'] += 1.8
    data['confidence_trend'] += 8
    data['inflation_trend'] += 0.5  # 勞動力增加推高通膨
    
    # 設置使用標記和冷卻
    data['policy_cooldowns']['active_skill'] = 4
    
    return True, "實施數位化培訓和彈性工作制度！高齡勞動參與率大幅提升，經濟活力增強"

def handle_taiwan_bet(player, target_country):
    """處理台灣主動技能：夾縫中求生存"""
    if player['country_code'] != 'TWN':
        return False, "只有台灣可以使用夾縫中求生存"
        
    data = player['country_data']
    
    if data.get('taiwan_bet_target'):
        return False, "已經在執行夾縫求生戰略"
    
    if not target_country:
        return False, "請選擇要搭順風車的國家"
    
    if target_country == 'TWN':
        return False, "不能選擇自己"
    
    # 設置賭注目標和持續時間
    data['taiwan_bet_target'] = target_country
    data['taiwan_bet_quarters_left'] = 3
    data['policy_cooldowns']['active_skill'] = 4
    
    return True, f"開始搭乘{target_country}的順風車！未來3季如果該國表現良好，台灣將獲得額外收益"

def handle_brazil_anticorruption(player):
    """處理巴西主動技能：反貪腐行動"""
    if player['country_code'] != 'BRA':
        return False, "只有巴西可以發動反貪腐行動"
        
    data = player['country_data']
    
    # 反貪腐的長期正面效果
    data['confidence_trend'] += 12
    data['gdp_trend'] += 2.0
    data['fiscal_deficit'] -= 2.0  # 減少貪腐損失
    data['unemployment_trend'] -= 0.8
    
    # 設置使用標記和冷卻
    data['policy_cooldowns']['active_skill'] = 4
    
    return True, "發動大規模反貪腐行動！政府效能大幅提升，民眾信心恢復，財政狀況改善"

def handle_saudi_transformation(player):
    """處理沙烏地主動技能：產業轉型"""
    if player['country_code'] != 'SAU':
        return False, "只有沙烏地阿拉伯可以進行產業轉型"
        
    data = player['country_data']
    
    transformation_level = data.get('saudi_transformation_level', 0)
    if transformation_level >= 3:
        return False, "產業轉型已達最高等級"
    
    # 提升轉型等級
    data['saudi_transformation_level'] = transformation_level + 1
    data['saudi_oil_dependency'] -= 0.25
    
    # 轉型效果
    data['gdp_trend'] += 1.5
    data['confidence_trend'] += 6
    data['unemployment_trend'] -= 0.5
    
    # 設置冷卻
    data['policy_cooldowns']['active_skill'] = 3
    
    level_name = ['初級', '中級', '高級'][data['saudi_transformation_level'] - 1]
    
    return True, f"推進{level_name}產業轉型！降低石油依賴度，經濟結構更加多元化"

def handle_oil_control(game, player, direction):
    """處理石油產量控制（沙烏地專屬）"""
    if player['country_code'] != 'SAU':
        return False, "只有沙烏地阿拉伯可以控制石油產量"
    
    if direction == 'increase':
        game.global_oil_price *= 0.9  # 增產降價
        game.global_oil_price = max(30, game.global_oil_price)
        
        # 對沙烏地的影響
        player['country_data']['gdp_trend'] += 0.8
        player['country_data']['fiscal_deficit'] -= 1.0
        
        game.add_log("🛢️ 沙烏地增加石油產量，國際油價下跌")
        return True, "增加石油產量，犧牲價格換取市場份額"
        
    elif direction == 'decrease':
        game.global_oil_price *= 1.15  # 減產升價
        game.global_oil_price = min(150, game.global_oil_price)
        
        # 對沙烏地的影響
        player['country_data']['gdp_trend'] += 1.5
        player['country_data']['fiscal_deficit'] -= 2.0
        
        game.add_log("🛢️ 沙烏地減少石油產量，國際油價上漲")
        return True, "減少石油產量，推高油價增加收入"


if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, debug=False, host='0.0.0.0', port=port)