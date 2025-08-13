# scoring.py - 評分計算模組
import math

class ScoringSystem:
    def __init__(self):
        # 共通指標權重設定 (總計490分)
        self.common_weights = {
            'gdp_growth': 98,      # 20%
            'inflation': 98,       # 20% 
            'unemployment': 74,    # 15%
            'confidence': 74,      # 15%
            'financial_stability': 49,  # 10%
            'fiscal_deficit': 49,  # 10%
            'cpi_stability': 49    # 10%
        }
        
        # 國家特色加分項 (每國210分)
        self.country_bonus = 210
        
        # 理想值範圍設定
        self.ideal_ranges = {
            'gdp_growth': (2.0, 4.0),
            'inflation': (1.5, 2.5),
            'unemployment': (3.0, 6.0),
            'confidence': (60, 80),
            'fiscal_deficit': (-1.0, 3.0)
        }
    
    def calculate_indicator_score(self, value, indicator, max_score, history=None):
        """計算單項指標得分"""
        ideal_min, ideal_max = self.ideal_ranges.get(indicator, (0, 100))
        
        # 基礎得分計算
        if ideal_min <= value <= ideal_max:
            base_score = max_score  # 滿分
        else:
            # 計算偏離程度
            if value < ideal_min:
                deviation = (ideal_min - value) / ideal_min
            else:
                deviation = (value - ideal_max) / ideal_max
            
            # 分段扣分
            if deviation <= 0.2:    # 輕微偏離
                base_score = max_score * 0.8
            elif deviation <= 0.5:  # 中度偏離
                base_score = max_score * 0.6
            elif deviation <= 1.0:  # 嚴重偏離
                base_score = max_score * 0.4
            else:                   # 危機水準
                base_score = max_score * 0.2
        
        # 穩定性調整
        stability_bonus = 0
        if history and len(history) >= 4:
            volatility = self.calculate_volatility(history)
            if indicator == 'gdp_growth' and volatility < 0.5:
                stability_bonus = 5
            elif indicator == 'inflation' and volatility < 0.3:
                stability_bonus = 5
            elif volatility > 1.0:
                stability_bonus = -10
        
        return max(0, base_score + stability_bonus)
    
    def calculate_volatility(self, history):
        """計算指標波動度（標準差）"""
        if len(history) < 2:
            return 0
        
        mean = sum(history) / len(history)
        variance = sum((x - mean) ** 2 for x in history) / len(history)
        return math.sqrt(variance)
    
    def calculate_financial_stability(self, country_data):
        """計算金融穩定性得分"""
        score = 0
        max_score = self.common_weights['financial_stability']
        
        # 股市波動度 (50%)
        stock_history = country_data.get('stock_history', [])
        if len(stock_history) >= 4:
            volatility = self.calculate_volatility(stock_history)
            if volatility < 15:
                score += max_score * 0.5
            elif volatility < 25:
                score += max_score * 0.4
            elif volatility < 35:
                score += max_score * 0.3
            else:
                score += max_score * 0.1
        else:
            score += max_score * 0.4  # 預設中等分數
        
        # 泡沫風險 (30%)
        bubble_risk = country_data.get('bubble_risk_level', 0)
        if bubble_risk < 10:
            score += max_score * 0.3
        elif bubble_risk < 25:
            score += max_score * 0.2
        elif bubble_risk < 50:
            score += max_score * 0.1
        
        # 匯率穩定性 (20%) - 暫時給予預設分數
        score += max_score * 0.15
        
        return score
    
    def calculate_country_bonus(self, player, all_players):
        """計算國家特色加分項"""
        country_code = player['country_code']
        data = player['country_data']
        bonus_score = 0
        
        if country_code == 'USA':
            # 通膨控制領先地位
            other_inflation = [p['country_data']['inflation'] 
                             for p in all_players.values() 
                             if p['country_code'] != 'USA']
            if other_inflation:
                avg_inflation = sum(other_inflation) / len(other_inflation)
                diff = avg_inflation - data['inflation']
                bonus_score = min(self.country_bonus, max(0, diff * 40))
        
        elif country_code == 'CHN':
            # GDP成長率領先
            other_gdp = [p['country_data']['gdp_growth'] 
                        for p in all_players.values() 
                        if p['country_code'] != 'CHN']
            if other_gdp:
                max_other_gdp = max(other_gdp)
                diff = data['gdp_growth'] - max_other_gdp
                bonus_score = min(self.country_bonus, max(0, diff * 60))
        
        elif country_code == 'JPN':
            # 通縮防治成效
            inflation = data['inflation']
            if inflation > 0:
                bonus_score = self.country_bonus
                # 持續正通膨獎勵檢查
                inflation_history = data.get('inflation_history', [])
                if len(inflation_history) >= 4 and all(x > 0 for x in inflation_history[-4:]):
                    bonus_score += 40
            elif inflation == 0:
                bonus_score = self.country_bonus * 0.75
            else:
                bonus_score = 0
        
        elif country_code == 'TWN':
            # 民眾信心卓越表現
            confidence = data['confidence']
            if confidence > 90:
                bonus_score = self.country_bonus
            elif confidence >= 85:
                bonus_score = self.country_bonus * 0.76
            elif confidence >= 80:
                bonus_score = self.country_bonus * 0.57
            else:
                bonus_score = 0
        
        elif country_code == 'BRA':
            # 財政赤字改善
            initial_deficit = data.get('initial_fiscal_deficit', data['fiscal_deficit'])
            current_deficit = data['fiscal_deficit']
            improvement = initial_deficit - current_deficit
            bonus_score = min(self.country_bonus, max(0, improvement * 70))
        
        elif country_code == 'SAU':
            # 經濟轉型進度
            dependency = data.get('saudi_oil_dependency', 100)
            if dependency <= 25:
                bonus_score = self.country_bonus
            elif dependency <= 50:
                bonus_score = self.country_bonus * 0.86
            elif dependency <= 75:
                bonus_score = self.country_bonus * 0.57
            else:
                bonus_score = self.country_bonus * 0.29
            
            # 持續轉型獎勵
            transformation_quarters = data.get('transformation_quarters', 0)
            bonus_score += transformation_quarters * 4
        
        return bonus_score
    
    def calculate_final_score(self, player, all_players, game_quarter):
        """計算最終得分"""
        data = player['country_data']
        total_score = 0
        score_details = {}
        
        # 共通指標評分
        indicators = {
            'gdp_growth': data['gdp_growth'],
            'inflation': data['inflation'],
            'unemployment': data['unemployment'],
            'confidence': data['confidence'],
            'fiscal_deficit': data['fiscal_deficit']
        }
        
        for indicator, value in indicators.items():
            if indicator in self.common_weights:
                history = data.get(f'{indicator}_history', [])
                score = self.calculate_indicator_score(
                    value, indicator, self.common_weights[indicator], history
                )
                total_score += score
                score_details[indicator] = score
        
        # 金融穩定性
        financial_score = self.calculate_financial_stability(data)
        total_score += financial_score
        score_details['financial_stability'] = financial_score
        
        # CPI穩定性 (暫時給予預設分數)
        cpi_score = self.common_weights['cpi_stability'] * 0.8
        total_score += cpi_score
        score_details['cpi_stability'] = cpi_score
        
        # 國家特色加分項
        country_bonus = self.calculate_country_bonus(player, all_players)
        total_score += country_bonus
        score_details['country_bonus'] = country_bonus
        
        # 相對表現獎勵
        relative_bonus = self.calculate_relative_bonus(player, all_players)
        total_score += relative_bonus
        score_details['relative_bonus'] = relative_bonus
        
        return {
            'total_score': round(total_score, 1),
            'details': score_details,
            'grade': self.get_grade(total_score)
        }
    
    def calculate_relative_bonus(self, player, all_players):
        """計算相對表現獎勵"""
        bonus = 0
        data = player['country_data']
        
        # 統計各指標排名
        indicators = ['gdp_growth', 'confidence', 'unemployment']
        top_half_count = 0
        first_place_count = 0
        
        for indicator in indicators:
            values = [(p['id'], p['country_data'][indicator]) for p in all_players.values()]
            
            # 失業率是越低越好，其他指標是越高越好
            reverse = (indicator == 'unemployment')
            values.sort(key=lambda x: x[1], reverse=not reverse)
            
            player_rank = next(i for i, (pid, _) in enumerate(values) if pid == player['id'])
            
            # 前50%加分
            if player_rank < len(values) / 2:
                top_half_count += 1
            
            # 第一名加分
            if player_rank == 0:
                first_place_count += 1
        
        bonus += top_half_count * 10  # 每項前50%加10分
        bonus += first_place_count * 20  # 每項第一名額外加20分
        
        return bonus
    
    def get_grade(self, total_score):
        """根據總分獲得評級"""
        if total_score >= 650:
            return 'S'
        elif total_score >= 600:
            return 'A'
        elif total_score >= 550:
            return 'B'
        elif total_score >= 500:
            return 'C'
        elif total_score >= 450:
            return 'D'
        else:
            return 'F'

# 全域評分系統實例
scoring_system = ScoringSystem()