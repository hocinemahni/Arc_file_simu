from collections import defaultdict, deque
from structures.file import File
from policy.policy import Policy
import math

class ARC_File_Policyv2lifetime(Policy):
    def __init__(self, cache_size, alpha, ssd_tier, hdd_tier):

        Policy.__init__(self, cache_size, alpha, ssd_tier, hdd_tier)
        self.p = 0
        self.mis_block = 0
        self.hit_block = 0
        #self.eviction_queue = deque()
        self.c = cache_size
        self.alpha = alpha
        self.block_size = 1024
        self.ssd_tier = ssd_tier
        self.hdd_tier = hdd_tier
        self.t1 = dict()
        self.t2 = dict()
        self.b1 = dict()
        self.b2 = dict()
        self.output_accumulator = ""
        self.ssd_cache = deque(maxlen=cache_size)
        self.hdd_cache = deque(maxlen=cache_size)
        self.hits_in_hdd_b1_b2 = 0  # Nouvelle métrique pour suivre les hits dans b1 et b2
        # New hit and miss counters
        self.hits = 0
        self.misses = 0
        self.false_misses = 0
        self.reel_misses = 0
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
        self.adapte_B1 = 0
        self.adapte_B2 = 0
        self.beta = 1
        self.file_access_timestamps = {}
        self.ssd_time = 0
        self.hdd_time = 0
        self.hdd_time_pref = 0
        self.ssd_time_evict = 0
        self.hdd_time_evict = 0
    def t1_max_size(self) -> int:
        return self.p

    def t2_max_size(self) -> int:
        return self.c - self.p

    def b1_max_size(self) -> int:
        return self.c - self.p

    def b2_max_size(self) -> int:
        return self.p

    def evict(self):
        # Ajustement d'alpha basé sur p.
        #if self.t1 and ((self.isinb2 and len(self.t1) == self.p) or (len(self.t1) > self.p)):
        if self.t1 and len(self.t1) > self.p:
            self.alpha = 0
            self.beta = 1
        elif self.t1 and len(self.t1) < self.p:
            self.alpha = 1
            self.beta = 0
        elif self.t1 == self.p:
            self.alpha = 1
            self.beta = 1
        file2score = defaultdict(int)
        files_to_evict_immediately = set()
        self.adapte_B1 = 0
        self.adapte_B2 = 0
        for i, block in enumerate(self.t1):
            file, offset = block
            
            if file.lifetime == 0 or ((self.file_access_timestamps[file] - file.firstAccessTime) <= 0) and file not in files_to_evict_immediately:
                files_to_evict_immediately.add(file)
            else:
                self.adapte_B1 += 1
                file2score[file] += i * self.beta
        for i, block in enumerate(self.t2):
            file, offset = block
            if file.lifetime == 0 or ((self.file_access_timestamps[file] - file.firstAccessTime) <= 0) and file not in files_to_evict_immediately:
                files_to_evict_immediately.add(file)
            else:
                self.adapte_B2 += 1
            
                file2score[file] += i * self.alpha

        if files_to_evict_immediately:
            # Évincer immédiatement les fichiers avec une durée de vie nulle
            #for filedeath in files_to_evict_immediately:

            expired_file = files_to_evict_immediately.pop()
            self.evicted_blocks_count += expired_file.size
            self.evicted_file_count += 1
            self.remove_all(expired_file)
            # Déplacer le fichier vers le HDD
            self.ssd_tier.remove_file(expired_file.name)

            self.hdd_tier.add_file(expired_file)


            # Calculer la taille des données à transférer en octets
            self.ssd_time_evict += ((expired_file.size * 1024) / self.ssd_tier.read_throughput) + self.ssd_tier.latency
            self.hdd_time_evict += ((expired_file.size * 1024) / self.hdd_tier.read_throughput) + self.hdd_tier.latency
            data_size_to_transfer = (expired_file.size * self.block_size)
            ssd_read_time = (data_size_to_transfer / self.ssd_tier.read_throughput)
            hdd_write_time = (data_size_to_transfer / self.hdd_tier.write_throughput)
            max_transfer_time = max(ssd_read_time, hdd_write_time)
            # Calculer le temps de migration
            self.migration_times += (max_transfer_time + self.ssd_tier.latency + self.hdd_tier.latency)
        else:
            file2score = {file: (score / file.size) * math.exp(- (file.lifetime - (self.file_access_timestamps[file] - file.firstAccessTime))) for file, score in file2score.items()}

            if not file2score:
                # No files with scores, so nothing to evict
                return
            worse_file = min(file2score, key=file2score.get)
            assert worse_file is not None
            assert worse_file.size > 0

            if (len(self.t1) + len(self.b1)) == self.c:
                if len(self.t1) < self.c:
                    if len(self.b1) >= self.adapte_B1 :
                        for _ in range(self.adapte_B1):

                            oldest_key = next(iter(self.b1))  # Obtient la première clé du dictionnaire
                            self.b1.pop(oldest_key)
                    else:
                        nombre_blocs_supprimes_b1 = len(self.b1)
                        self.b1.clear()
                        for _ in range(worse_file.size - nombre_blocs_supprimes_b1):
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
                        for _ in range(worse_file.size - nombre_blocs_supprimes_b2):
                            oldest_key2 = next(iter(self.b1))  # Obtient la première clé du dictionnaire
                            self.b1.pop(oldest_key2)
            self.remove_all(worse_file)
            # Déplacer le fichier vers le HDD
            self.ssd_tier.remove_file(worse_file.name)
            #self.hdd_cache.appendleft(worse_file)
            self.hdd_tier.add_file(worse_file)
            self.evicted_blocks_count += worse_file.size
            self.evicted_file_count += 1

            # Calculer la taille des données à transférer en octets

            data_size_to_transfer = (worse_file.size * self.block_size)
            self.ssd_time_evict += (data_size_to_transfer / self.ssd_tier.read_throughput) + self.ssd_tier.latency
            self.hdd_time_evict += (data_size_to_transfer / self.hdd_tier.read_throughput) + self.hdd_tier.latency
            ssd_read_time = (data_size_to_transfer / self.ssd_tier.read_throughput)
            hdd_write_time = (data_size_to_transfer / self.hdd_tier.write_throughput)
            max_transfer_time = max(ssd_read_time, hdd_write_time)
            # Calculer le temps de migration
            self.migration_times += (max_transfer_time + self.ssd_tier.latency + self.hdd_tier.latency)
            #print(f'migrate time for this file , {worse_file} , avec la tail {worse_file.size}est  {self.migration_times}')

    def remove_all(self, file: File):
        """
        Remove all blocks of a file that are in t1 or t2, and add them to b1 and b2, respectively
        """
        # logging.debug(f'File {file} marked for unload. State before unload:')
        # logging.debug(self)
        blocks_t1 = [block for block in self.t1 if block[0] == file]
        blocks_t2 = [block for block in self.t2 if block[0] == file]
        for block in blocks_t1:
            del self.t1[block]
            self.b1[block] = None

        for block in blocks_t2:
            del self.t2[block]
            self.b2[block] = None

        self.file2tier[file] = 0
        del self.file2blocks[file]

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
        if file.size <= (self.c - (len(self.t1) + len(self.t2))):
            for block_offset in range(file.size):
                # A block is identified by its file and offset
                block = (file, block_offset)

                # We add the block to the file's block list
                self.file2blocks[file].add(block)

                # We add the block to t1's list
                tier[block] = None

        else:
            self.evict()

    def move_file_to(self, file, tier):
        self.remove_all_hard(file)
        self.load_file_to(file, tier)

    def on_io(self, file, timestamp, requestType, offsetStart, offsetEnd):
        self.file_access_timestamps[file] = timestamp
        self.total_time = 0
        self.hdd_time_pref =0
        self.ssd_time = 0
        self.hdd_time = 0
        self.ssd_time_evict = 0
        self.hdd_time_evict = 0
        self.write_times = self.read_times = self.prefetch_times = self.migration_times = 0
        self.isinb2 = False
        #io_blocks = {(file, offsetStart + i) for i in range(offsetEnd - offsetStart)}


        new_file = False
        if not self.file2blocks[file]:
            if self.hdd_tier.is_file_in_tier(file.name):
                self.hdd_time += ((offsetStart - offsetEnd) * self.block_size / self.hdd_tier.read_throughput) + self.hdd_tier.latency
                self.hdd_tier.remove_file(file.name)
                self.ssd_tier.add_file(file)
                #print(f'File {file} is not in cache, loading in t1.')
                new_file = True
                self.false_misses += 1
                #print(file.size)
                self.load_file_to(file, self.t1)
                self.file2tier[file] = 1
            else:
                if file.size > self.c:
                    new_file = True
                    self.hdd_tier.add_file(file)
                    #self.write_times += ((file.size * self.block_size) / self.hdd_tier.write_throughput)
                    self.hdd_time += ((offsetStart - offsetEnd) * self.block_size / self.hdd_tier.read_throughput) + self.hdd_tier.latency
                else:
                    new_file = True
                    self.false_misses += 1
                    # print(file.size)
                    self.load_file_to(file, self.t1)
                    self.ssd_tier.add_file(file)
                    self.ssd_time += ((file.size * self.block_size) / self.ssd_tier.write_throughput) + self.ssd_tier.latency
                    #self.write_times += ((file.size * self.block_size) / self.ssd_tier.write_throughput) + self.ssd_tier.latency    # lat read
                    self.file2tier[file] = 1

                # self.ssd_cache.appendleft(file)
                # self.ssd_tier.add(file)
                # Check if all blocks of the I/O are in T1 or T2
        # all_blocks_in_cache = all(
        #     (block in self.t1.keys() and new_file == False) or block in self.t2.keys() for block in io_blocks)
        # # Count hits and misses for this I/O
        # if all_blocks_in_cache:
        #     self.hits += 1
        # else:
        #     self.misses += 1
        for block_offset in range(offsetStart, offsetEnd):
            block = (file, block_offset)
            if block in self.t1 and (new_file == False) or block in self.t2:
                #hits = True
                self.hits += 1
            else:
                # Si le bloc n'est pas dans t1 ou t2, c'est un 'miss'
                #hits = False
                self.misses += 1
            # Vérifier si le bloc est dans t1 ou t2
            if block in self.t1:
                if not new_file:
                    #self.hits += 1
                    self.ssd_time += (self.block_size / self.ssd_tier.read_throughput) + self.ssd_tier.latency
                    #self.read_times += (self.block_size / self.ssd_tier.read_throughput)
                    del self.t1[block]
                    self.t2[block] = None
                else:
                    self.read_times += (self.block_size / self.ssd_tier.read_throughput)
                    #self.misses += 1
            elif block in self.t2:
                #self.hits += 1
                #self.hit_block += 1
                self.ssd_time += (self.block_size / self.ssd_tier.read_throughput) + self.ssd_tier.latency
                #self.read_times += (self.block_size / self.ssd_tier.read_throughput)
                del self.t2[block]
                self.t2[block] = None  # Déplacer le bloc à la fin de T2 pour maintenir l'ordre d'accès
            elif block in self.b1:
                #self.misses += 1
                #self.mis_block += 1
                self.p = min(self.p + max(round(len(self.b2) / (len(self.b1))), file.size), self.c)
                self.move_file_to(file, self.t2)
                # self.hdd_cache.remove(file)
                self.hdd_tier.remove_file(file.name)
                #self.ssd_cache.appendleft(file)
                self.ssd_tier.add_file(file)
                self.hits_in_hdd_b1_b2 += 1
                # Calculer le temps nécessaire pour lire le fichier depuis le HDD
                hdd_read_time = ((file.size * self.block_size) / self.hdd_tier.read_throughput)

                # Calculer le temps nécessaire pour écrire le fichier sur le SSD
                ssd_write_time = ((file.size * self.block_size) / self.ssd_tier.write_throughput)

                # Si les opérations de lecture et d'écriture sont en parallèle,
                # prendre le maximum des deux temps
                max_transfer_time = max(hdd_read_time, ssd_write_time)

                # Additionner le temps de transfert maximum et les latences des deux tiers
                total_prefetch_time = (max_transfer_time + self.ssd_tier.latency + self.hdd_tier.latency)
                self.hdd_time_pref += ((offsetStart - offsetEnd) * self.block_size / self.hdd_tier.read_throughput) + self.hdd_tier.latency
                # Mettre à jour le temps total de préchargement
                self.prefetch_times += total_prefetch_time
                #break

            elif block in self.b2:
                #self.misses += 1
                #self.mis_block += 1

                self.p = max(self.p - max(round(len(self.b1) / (len(self.b2))), file.size), 0)
                # self.evict()
                self.isinb2 = True
                self.move_file_to(file, self.t2)
                # self.hdd_cache.remove(file)
                self.hdd_tier.remove_file(file.name)
                #self.ssd_cache.appendleft(file)
                self.ssd_tier.add_file(file)
                self.hits_in_hdd_b1_b2 += 1
                # Calculer le temps nécessaire pour lire le fichier depuis le HDD
                hdd_read_time = ((file.size * self.block_size) / self.hdd_tier.read_throughput)

                # Calculer le temps nécessaire pour écrire le fichier sur le SSD
                ssd_write_time = ((file.size * self.block_size) / self.ssd_tier.write_throughput)

                # Si les opérations de lecture et d'écriture sont en parallèle,
                # prendre le maximum des deux temps
                max_transfer_time = max(hdd_read_time, ssd_write_time)

                # Additionner le temps de transfert maximum et les latences des deux tiers
                total_prefetch_time = (max_transfer_time + self.ssd_tier.latency + self.hdd_tier.latency)
                self.hdd_time_pref += ((offsetStart - offsetEnd) * self.block_size / self.hdd_tier.read_throughput) + self.hdd_tier.latency
                # Mettre à jour le temps total de préchargement
                self.prefetch_times += total_prefetch_time
                #break

        #self.reel_misses = self.misses - self.false_misses
        #self.total_time = self.ssd_time + self.hdd_time + self.hdd_time_pref + self.hdd_time_evict
        self.total_time = self.ssd_time + self.hdd_time + self.hdd_time_pref + self.ssd_time_evict + self.hdd_time_evict 
        #self.total_time = (self.prefetch_times + self.read_times + self.write_times + self.migration_times)
        print('hits', self.hits)
        print('misses', self.misses)
        # print('nombre de fichiers évincés ', self.evicted_file_count)
        # print('nombre de blocks evincés ', self.evicted_blocks_count)
        #print('size of t1 and t2', len(self.t1) + len(self.t2))
        #print('size of b1 and b2', len(self.b1) + len(self.b2))
        #print('size of t1 ', len(self.t1))
        # print('size of t2', len(self.t2))
        # print('size of b1 ', len(self.b1))
        # print('size of b2', len(self.b2))
        # print('misblock block', self.mis_block)
        # print('hitblock block', self.hit_block)
