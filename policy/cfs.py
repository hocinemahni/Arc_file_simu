from collections import defaultdict, deque, OrderedDict
from structures.file import File
from policy.policy import Policy
import math
import numpy as np


class CFS_ARC(Policy):
    def __init__(self, cache_size, alpha, ssd_tier, hdd_tier):
        Policy.__init__(self, cache_size, alpha, ssd_tier, hdd_tier)
        self.p = 0
        self.eviction_queue = deque()
        self.c = cache_size
        self.alpha = 0
        self.beta = 0
        self.block_size = 1024
        self.ssd_tier = ssd_tier
        self.hdd_tier = hdd_tier
        # self.t1 = dict()
        # self.t2 = dict()
        # self.b1 = dict()
        # self.b2 = dict()
        self.t1 = OrderedDict()
        self.t2 = OrderedDict()
        self.b1 = OrderedDict()
        self.b2 = OrderedDict()
        self.ssd_cache = deque(maxlen=cache_size)
        self.hdd_cache = deque(maxlen=cache_size)
        self.hits_in_hdd_b1_b2 = 0
        self.file_access_timestamps = {}
        # New 'hit' and 'miss' counters
        self.is_in_b2 = False
        self.hits = 0
        self.misses = 0
        self.false_misses = 0
        self.read_times = 0
        self.write_times = 0
        self.total_time = 0
        self.prefetch_times = 0
        self.migration_times_evict = 0
        self.total_eviction_time = 0
        # nombres de blocks évincé
        self.evicted_blocks_count = 0
        self.evicted_file_count = 0
        self.file2blocks = defaultdict(set)
        self.file2tier = defaultdict(int)
        self.migration_times = 0
        self.ssd_time = 0
        self.hdd_time = 0
        self.hdd_time_pref = 0
        self.ssd_time_evict = 0
        self.hdd_time_evict = 0
        self.ssd_time_pref = 0
        self.files_to_evict_immediately = set()
        self.adapte_B1 = 0
        self.adapte_B2 = 0
        self.unique_files = set()
    def calculate_vruntime_for_file(self, file):
        # Calcul de vruntime_min comme indiqué
        num_files_in_ssd = len(self.ssd_tier.files)
        total_ssd_size = self.ssd_tier.size  
        ssd_throughput = self.ssd_tier.read_throughput  
        ssd_latency = self.ssd_tier.latency  
        if num_files_in_ssd > 0:
            vruntime_min = (total_ssd_size / num_files_in_ssd) * 1 / (ssd_throughput + ssd_latency)
        else:
            vruntime_min = np.inf  # Pour éviter la division par zéro

        # Calcul du poids du fichier
        file_weight = max(1, file.lifetime - (
                    self.file_access_timestamps[file] - file.entry_time_ssd))  # DSSD est approximé par current_time - entry_time_ssd

        # Calcul du vruntime actuel ajusté
        total_weight = sum(file.lifetime - (self.file_access_timestamps[file] - file.entry_time_ssd) for file in self.unique_files)

        vruntime_adjusted = file_weight / total_weight

        # Mise à jour du vruntime du fichier
        #file.vruntime = max(vruntime_min, vruntime_adjusted)
        # Mise à jour du vruntime du fichier en utilisant l'équation fournie
        #file.vruntime = max(vruntime_min, file.vruntime * (file_weight / total_weight))
        file.vruntime = max(vruntime_min, file.vruntime * vruntime_adjusted)
    def evict(self):

        for tier in (self.t1, self.t2):
            for (file, _) in tier:
                self.unique_files.add(file)

        # parcourir l'ensemble des fichiers uniques pour appliquer la logique d'éviction
        for file in self.unique_files:
            
            if file.lifetime == 0 or ((self.file_access_timestamps[file] - file.lastAccessTime) <= 0):
                if file not in self.files_to_evict_immediately:
                    self.files_to_evict_immediately.add(file)
                    self.eviction_queue.append(file)
        for file in self.unique_files:
            self.calculate_vruntime_for_file(file)

            # Après le calcul du vruntime pour chaque fichier, on procéde à l'éviction basée sur vruntime

        files_sorted_by_vruntime = sorted(self.unique_files, key=lambda f: f.vruntime, reverse=True)
        # Sélectionner le fichier avec le vruntime le plus élevé/faible pour l'éviction
        if files_sorted_by_vruntime:
            worse_file = files_sorted_by_vruntime[0]  # Le fichier avec le vruntime le plus élevé/faible
            # print('worse file :', worse_file.name)
            assert worse_file is not None
            assert worse_file.size > 0

            self.eviction_queue.append(worse_file)


    def actual_evict(self):
        self.ssd_time_evict = 0
        self.hdd_time_evict = 0
        if not self.eviction_queue:
            return

        file_to_evict = self.eviction_queue.popleft()
        if file_to_evict in self.files_to_evict_immediately:
            self.files_to_evict_immediately.remove(file_to_evict)
        # print('file to evict:', file_to_evict.name)
        if len(self.t1) + len(self.b1) == self.c:
            if len(self.t1) < self.c:
                if len(self.b1) >= self.adapte_B1:
                    for _ in range(self.adapte_B1):
                        oldest_key = next(iter(self.b1))  # Obtient la première clé du dictionnaire
                        self.b1.pop(oldest_key)
                else:
                    nombre_blocs_supprimes_b1 = len(self.b1)
                    self.b1.clear()
                    for _ in range(file_to_evict.size - nombre_blocs_supprimes_b1):
                        # print('hello 2', _)
                        oldest_key2 = next(iter(self.b2))  # Obtient la première clé du dictionnaire
                        self.b2.pop(oldest_key2)

        elif (len(self.t1) + len(self.t2) + len(self.b1) + len(self.b2)) >= self.c:
            if (len(self.t1) + len(self.t2) + len(self.b1) + len(self.b2)) == (self.c * 2):
                if len(self.b2) >= self.adapte_B2:
                    for _ in range(self.adapte_B2):
                        oldest_key2 = next(iter(self.b2))  # Obtient la première clé du dictionnaire
                        self.b2.pop(oldest_key2)
                else:

                    nombre_blocs_supprimes_b2 = len(self.b2)
                    self.b2.clear()
                    if self.b1:
                        for _ in range(file_to_evict.size - nombre_blocs_supprimes_b2):
                            # print('hello 2', _)
                            oldest_key2 = next(iter(self.b1))  # Obtient la première clé du dictionnaire
                            self.b1.pop(oldest_key2)

        # Calculer la taille des données à transférer
        data_size_to_transfer = file_to_evict.size * self.block_size
        # ssd_read_time = data_size_to_transfer / self.ssd_tier.read_throughput
        self.ssd_time_evict = (data_size_to_transfer / self.ssd_tier.read_throughput) + self.ssd_tier.latency
        self.hdd_time_evict = (data_size_to_transfer / self.hdd_tier.write_throughput) + self.hdd_tier.latency
        # Traiter tous les blocs associés au fichier
        for block in self.file2blocks[file_to_evict]:
            if block in self.t1:
                del self.t1[block]
                self.b1[block] = None  # Ajouter le bloc à b1
            elif block in self.t2:
                del self.t2[block]
                self.b2[block] = None  # Ajouter le bloc à b2
        # file_to_evict.is_eviction_pending = False
        self.ssd_tier.remove_file(file_to_evict.name)
        self.hdd_tier.add_file(file_to_evict)
        self.file2tier[file_to_evict] = 0
        del self.file2blocks[file_to_evict]
        # self.eviction_queue.remove(file_to_evict)
        # Mettre à jour les compteurs d'éviction
        self.evicted_blocks_count += file_to_evict.size
        self.evicted_file_count += 1

    def remove_all(self, file: File):

        """
        Remove all blocks of a file that are in t1 or t2, and add them to b1 and b2, respectively.
        """
        if file in self.file2blocks:
            for block in self.file2blocks[file]:
                if block in self.t1:
                    del self.t1[block]
                    self.b1[block] = None
                elif block in self.t2:
                    del self.t2[block]
                    self.b2[block] = None

            del self.file2blocks[file]
            self.file2tier[file] = 0

    def remove_all_hard(self, file: File):
        """
        Remove all blocks of a file from t1, t2, b1 or b2
        """
        # logging.debug(f'File {file} marked for unload. State before unload:')
        # logging.debug(self)
        blocks = self.file2blocks[file]
        for block in blocks:
            if block in self.t1.keys():
                del self.t1[block]
            elif block in self.t2.keys():
                del self.t2[block]
            elif block in self.b1.keys():
                del self.b1[block]
            elif block in self.b2.keys():
                del self.b2[block]
        del self.file2blocks[file]
        self.file2tier[file] = 0

    def load_file_to(self, file, tier):

        # if file.size > self.c:
        #     self.hdd_tier.add_file(file)
        #     self.hdd_time += ((file.size * self.block_size) / self.hdd_tier.write_throughput) + self.hdd_tier.latency
        #
        # else:
            space_needed = file.size
            space_available = self.c - (len(self.t1) + len(self.t2))
            if space_needed > space_available:

                self.evict()
                space_available = self.c - (len(self.t1) + len(self.t2))
            for block_offset in range(file.size):
                # A block is identified by its file and offset
                block = (file, block_offset)

                # We add the block to the file's block list
                self.file2blocks[file].add(block)

                # We add the block to t1's list
                tier[block] = None

    def move_file_to(self, file, tier):
        self.remove_all_hard(file)
        self.load_file_to(file, tier)

    def on_io(self, file: File, timestamp, requestType, offsetStart, offsetEnd):
        self.total_time = 0
        self.ssd_time_pref = 0
        self.hdd_time_pref = 0
        self.file_access_timestamps[file] = timestamp
        self.ssd_time = 0
        self.hdd_time = 0
        self.ssd_time_evict = 0
        self.hdd_time_evict = 0
        self.write_times = self.read_times = self.prefetch_times = self.migration_times = 0
        self.is_in_b2 = False
        if file in self.eviction_queue:
            self.eviction_queue.remove(file)
        new_file = False
        if not self.file2blocks[file]:
            if self.hdd_tier.is_file_in_tier(file.name):
                if file.size <= self.c:
                    new_file = False
                    self.hdd_tier.remove_file(file.name)
                    self.ssd_tier.add_file(file)
                    file.update_entry_time_ssd(timestamp)
                    # print(f'File {file.size} is not in cache, loading in t1.')
                    self.false_misses += 1
                    self.remove_all_hard(file)
                    self.load_file_to(file, self.t1)
                    self.file2tier[file] = 1
                    # Calculer le temps nécessaire pour lire le fichier depuis le HDD
                    self.hdd_time += ((file.size * self.block_size) / self.hdd_tier.read_throughput) + \
                        self.hdd_tier.latency

                    # Calculer le temps nécessaire pour écrire le fichier sur le SSD
                    self.ssd_time += ((file.size * self.block_size) / self.ssd_tier.write_throughput) + \
                        self.ssd_tier.latency
                else:
                    if file.size > self.c:
                        new_file = False
                        # self.hdd_tier.add_file(file)
            else:
                if file.size > self.c:
                    new_file = True
                    self.hdd_tier.add_file(file)
                    self.hdd_time += ((file.size * self.block_size) / self.hdd_tier.write_throughput) + \
                        self.hdd_tier.latency
                    # print(f'File {file} is not in cache, loading in t1.')
                else:
                    new_file = True
                    self.false_misses += 1
                    self.remove_all_hard(file)
                    self.load_file_to(file, self.t1)
                    file.update_entry_time_ssd(timestamp)

                    self.ssd_time += ((file.size * self.block_size) / self.ssd_tier.write_throughput) + \
                        self.ssd_tier.latency
                    self.file2tier[file] = 1
                    self.ssd_tier.add_file(file)
        for block_offset in range(offsetStart, offsetEnd):
            block = (file, block_offset)
            # if file in self.eviction_queue :
            #   self.eviction_queue.remove(file)
            # if (block in self.t1 and new_file is False) or (block in self.t2 and new_file is False):
            if (block in self.t1 and new_file is False and requestType != 'create') or block in self.t2:
                self.hits += 1
            else:
                # Si le bloc n'est pas dans t1 ou t2, c'est un 'miss'
                self.misses += 1
            # Vérifier si le bloc est dans t1 ou t2
            if block in self.t1:
                if not new_file:
                    # self.hits += 1
                    file.update_entry_time_ssd(timestamp)
                    self.ssd_time += (self.block_size / self.ssd_tier.read_throughput) + self.ssd_tier.latency
                    #self.read_times += (self.block_size / self.ssd_tier.read_throughput)
                    del self.t1[block]
                    self.t2[block] = None
                else:
                    # self.misses += 1
                    self.ssd_time += (self.block_size / self.ssd_tier.read_throughput) + self.ssd_tier.latency

            elif block in self.t2:
                # self.hits += 1
                # self.hit_block += 1
                file.update_entry_time_ssd(timestamp)
                self.ssd_time += (self.block_size / self.ssd_tier.read_throughput) + self.ssd_tier.latency
                #self.read_times += (self.block_size / self.ssd_tier.read_throughput)
                del self.t2[block]
                self.t2[block] = None  # Déplacer le bloc à la fin de T2 pour maintenir l'ordre d'accès
            elif block in self.b1:
                # self.misses += 1
                # self.mis_block += 1
                self.p = min(self.p + max(round(len(self.b2) / (len(self.b1))), file.size), self.c)
                self.move_file_to(file, self.t2)
                self.hdd_tier.remove_file(file.name)
                self.ssd_tier.add_file(file)
                file.update_entry_time_ssd(timestamp)
                self.hits_in_hdd_b1_b2 += 1
                # Calculer le temps nécessaire pour lire le fichier depuis le HDD
                self.hdd_time += ((file.size * self.block_size) / self.hdd_tier.read_throughput) + \
                    self.hdd_tier.latency

                # Calculer le temps nécessaire pour écrire le fichier sur le SSD
                self.ssd_time += ((file.size * self.block_size) / self.ssd_tier.write_throughput) + \
                    self.ssd_tier.latency

            elif block in self.b2:
                # self.misses += 1
                # self.mis_block += 1
                # print('hi b2', file.name)
                self.p = max(self.p - max(round(len(self.b1) / (len(self.b2))), file.size), 0)
                # self.evict()
                self.is_in_b2 = True
                self.move_file_to(file, self.t2)
                # self.hdd_cache.remove(file)
                self.hdd_tier.remove_file(file.name)
                self.ssd_tier.add_file(file)
                file.update_entry_time_ssd(timestamp)
                self.hits_in_hdd_b1_b2 += 1
                # Calculer le temps nécessaire pour lire le fichier depuis le HDD
                self.hdd_time += ((file.size * self.block_size) / self.hdd_tier.read_throughput) + \
                    self.hdd_tier.latency

                # Calculer le temps nécessaire pour écrire le fichier sur le SSD
                self.ssd_time += ((file.size * self.block_size) / self.ssd_tier.write_throughput) + \
                    self.ssd_tier.latency
            elif self.hdd_tier.is_file_in_tier(file.name) and not self.ssd_tier.is_file_in_tier(file.name):
                self.hdd_time += (self.block_size / self.hdd_tier.read_throughput) + self.hdd_tier.latency
        # self.reel_misses = self.misses - self.false_misses
        self.total_time = self.ssd_time + self.hdd_time + self.ssd_time_evict + self.hdd_time_evict

        # self.total_time = (self.prefetch_times + self.read_times + self.write_times)
        # print('hits', self.hits)
        # print('misses', self.misses)
        # # print('nombre de fichiers évincés ', self.evicted_file_count)
        # # print('size of t1 and t2', len(self.t1) + len(self.t2))
        # print('nombre de blocks évincés ', self.evicted_blocks_count)
        # print(len(self.ssd_tier.files))
        # print((self.ssd_tier.size))
        # print((self.ssd_tier.files))
        # print(len(self.file2blocks))
        # print(self.t1)
        # print(self.t2)
        #print(self.ssd_tier.__str__())